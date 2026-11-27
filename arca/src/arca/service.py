"""Arca-Service: lokale HTTP-API für das Dashboard (Tab "Arca") und den Terminal-Server.

Lauscht nur auf 127.0.0.1. Er ist die einzige Komponente, die vault.db öffnet; Claude erreicht ihn nicht
(keine Built-in-Tools im Terminal, nur der MCP-Server auf visible.db).

    GET  /status       freigegeben ja/nein, letzte Freigabe
    GET  /tables       B (Originale), A (visible.db), Spalten, Audit-Log
    POST /preview      {"columns": [...]} -> Vorschau (nicht freigegeben)
    POST /release      {"preview_id": "..."} -> schreibt visible.db
    POST /revoke       visible.db leeren
    POST /retranslate  {"text": "..."} -> Klarnamen, nur zur Anzeige in der UI
    POST /documents    multipart (mandat_id, file): Text bzw. lokales OCR -> vault.db
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from arca import vault_db
from arca.anonymize import ArcaAnonymizer, PreviewError
from arca.config import Config
from arca.documents import MAX_BYTES, UploadError, add_document, ocr_engine
from arca.release import ReleaseError, audit_log, init_visible, release, released, revoke


class PreviewRequest(BaseModel):
    columns: list[str]


class ReleaseRequest(BaseModel):
    preview_id: str


class RetranslateRequest(BaseModel):
    text: str


def _visible(path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (vault_db.TABLE,)).fetchone():
            return {"columns": [], "rows": []}
        cur = conn.execute(f'SELECT * FROM "{vault_db.TABLE}" ORDER BY zeile')
        return {"columns": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}
    finally:
        conn.close()


def create_app(config: Config | None = None, anonymizer: ArcaAnonymizer | None = None) -> FastAPI:
    cfg = config or Config.from_env()
    conn = vault_db.connect(cfg.vault_path)
    vault_db.seed(conn)
    init_visible(cfg.visible_path)
    arca = anonymizer or ArcaAnonymizer(conn, cfg.secret)
    lock = threading.Lock()
    app = FastAPI(title="Arca", version="0.1.0")

    def last_release() -> dict | None:
        return next((e for e in audit_log(conn) if e["action"] in ("release", "revoke")), None)

    @app.get("/status")
    def status() -> dict:
        with lock:
            return {"released": released(cfg.visible_path), "last": last_release()}

    @app.get("/tables")
    def tables() -> dict:
        with lock:
            return {
                "columns": [{"key": k, "label": label, "kind": kind} for k, (label, kind) in vault_db.COLUMNS.items()],
                "vault": vault_db.rows(conn),
                "visible": _visible(cfg.visible_path),
                "released": released(cfg.visible_path),
                "audit": audit_log(conn, 20),
                "documents": [dict(r) for r in conn.execute(
                    "SELECT id, mandat_id, dateiname, format, ocr, length(text) AS chars, created_at "
                    "FROM dokumente ORDER BY id DESC")],
                "ocr": ocr_engine() is not None,
            }

    @app.post("/preview")
    def preview(req: PreviewRequest) -> dict:
        with lock:
            try:
                return arca.preview(req.columns)
            except PreviewError as exc:
                raise HTTPException(400, str(exc)) from exc

    @app.post("/release")
    def release_(req: ReleaseRequest) -> dict:
        with lock:
            try:
                return release(conn, cfg.visible_path, req.preview_id)
            except ReleaseError as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.post("/revoke")
    def revoke_() -> dict:
        with lock:
            return revoke(conn, cfg.visible_path)

    @app.post("/retranslate")
    def retranslate(req: RetranslateRequest) -> dict:
        with lock:
            text, spans = arca.vault.retranslate(req.text)
            return {"text": text, "spans": spans}

    @app.post("/documents")
    def documents(mandat_id: int = Form(...), file: UploadFile = File(...)) -> dict:
        data = file.file.read(MAX_BYTES + 1)  # synchron: OCR läuft im Threadpool, nicht in der Event-Loop
        with lock:
            try:
                doc = add_document(conn, mandat_id, file.filename or "dokument", data)
            except UploadError as exc:
                raise HTTPException(400, str(exc)) from exc
            conn.execute("INSERT INTO audit_log (created_at, action, columns, row_count, preview_id) "
                         "VALUES (?, 'document', ?, 1, NULL)", (time.time(), json.dumps(["dokumente"])))
            conn.commit()
            return doc

    return app


def run() -> None:  # pragma: no cover
    import uvicorn

    import os

    # Lokal nur 127.0.0.1; im Container 0.0.0.0, aber nur im internen Docker-Netz erreichbar (kein Port nach außen).
    uvicorn.run(create_app(), host=os.environ.get("ARCA_HOST", "127.0.0.1"), port=int(os.environ.get("ARCA_PORT", 8100)))
