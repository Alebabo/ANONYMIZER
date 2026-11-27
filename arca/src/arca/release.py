"""Freigabe: eine Vorschau aus vault.db wird nach visible.db geschrieben.

* visible.db wird bei jeder Freigabe neu aufgebaut (temporäre Datei, dann atomar ersetzt). Sie enthält genau
  die Spalten und Werte der freigegebenen Vorschau, keine IDs aus vault.db, kein Mapping.
* Vor dem Schreiben eine letzte, unabhängige Prüfung: kein Originalwert aus vault.db (Mandant, Firma, Gegner,
  Aktenzeichen, Ort, Nachnamen) darf in einer Zelle stehen. Sonst wird nichts geschrieben.
* Pflichtprüfung: ohne ausdrückliche Bestätigung und ohne Namen der prüfenden Person keine Freigabe.
* Jede Freigabe und jeder Widerruf landet mit Person, Vergröberung und Zahl der Prüfhinweise im Audit-Log.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

from arca import vault_db
from arca.anonymize import STRUCTURED

VISIBLE_TABLE = vault_db.TABLE


class ReleaseError(RuntimeError):
    pass


def init_visible(path: Path) -> None:
    """Leere visible.db anlegen (ohne Tabellen), falls sie fehlt."""
    if not path.exists():
        sqlite3.connect(path).close()


def released(path: Path) -> bool:
    if not path.exists():
        return False
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0
    finally:
        conn.close()


def originals(vault: sqlite3.Connection) -> list[str]:
    """Alle Werte, die nie in visible.db stehen dürfen."""
    values: set[str] = set()
    for row in vault_db.rows(vault):
        for col, (_, kind) in vault_db.COLUMNS.items():
            if kind in STRUCTURED and row[col].strip():
                values.add(row[col].strip())
                if kind in ("person", "party"):
                    values.update(w for w in row[col].split() if len(w) >= 3)
    values.update(r["value"] for r in vault.execute("SELECT value FROM token_map"))
    return sorted(values, key=len, reverse=True)


def find_leaks(cells: list[str], forbidden: list[str]) -> list[str]:
    if not forbidden:
        return []
    pattern = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, forbidden)) + r")(?!\w)", re.IGNORECASE)
    return sorted({m.group(1) for cell in cells for m in pattern.finditer(cell)})


def _write_visible(path: Path, columns: list[str], rows: list[dict]) -> None:
    tmp = path.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        cols = ", ".join(f'"{c}" TEXT' for c in columns)
        conn.execute(f'CREATE TABLE "{VISIBLE_TABLE}" (zeile INTEGER PRIMARY KEY, {cols})')
        placeholders = ", ".join("?" for _ in range(len(columns) + 1))
        conn.executemany(f'INSERT INTO "{VISIBLE_TABLE}" VALUES ({placeholders})',
                         [(r["zeile"], *(r["cells"][c]["value"] for c in columns)) for r in rows])
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, path)


def audit(vault: sqlite3.Connection, action: str, columns: list[str], row_count: int, preview_id: str | None,
          actor: str | None = None, details: dict | None = None) -> dict:
    entry = {"created_at": time.time(), "action": action, "columns": columns, "row_count": row_count,
             "preview_id": preview_id, "actor": actor, "details": details}
    vault.execute("INSERT INTO audit_log (created_at, action, columns, row_count, preview_id, actor, details) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (entry["created_at"], action, json.dumps(columns), row_count, preview_id, actor,
                   json.dumps(details) if details is not None else None))
    vault.commit()
    return entry


def release(vault: sqlite3.Connection, visible_path: Path, preview_id: str, actor: str = "",
            confirmed: bool = False) -> dict:
    if not confirmed or not actor.strip():
        raise ReleaseError("Freigabe nur nach bestätigter Prüfung der Vorschau durch eine angemeldete Person")
    row = vault.execute("SELECT columns, payload FROM preview WHERE id = ?", (preview_id,)).fetchone()
    if row is None:
        raise ReleaseError("Vorschau nicht gefunden. Erst anonymisieren.")
    columns: list[str] = json.loads(row["columns"])
    payload = json.loads(row["payload"])
    rows: list[dict] = payload["rows"] if isinstance(payload, dict) else payload
    details = {k: payload.get(k) for k in ("options", "hints")} if isinstance(payload, dict) else {}
    leaks = find_leaks([r["cells"][c]["value"] for r in rows for c in columns], originals(vault))
    if leaks:
        raise ReleaseError(f"Freigabe gestoppt: {len(leaks)} Originalwert(e) noch in der Vorschau")
    _write_visible(visible_path, columns, rows)
    return audit(vault, "release", columns, len(rows), preview_id, actor, details)


def revoke(vault: sqlite3.Connection, visible_path: Path, actor: str | None = None) -> dict:
    """Freigabe zurückziehen: visible.db wird wieder leer."""
    visible_path.unlink(missing_ok=True)
    init_visible(visible_path)
    return audit(vault, "revoke", [], 0, None, actor)


def audit_log(vault: sqlite3.Connection, limit: int = 50) -> list[dict]:
    return [{**dict(r), "columns": json.loads(r["columns"]), "details": json.loads(r["details"] or "null")}
            for r in vault.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]
