"""Dokumente zu einem Mandat: Text (bei Scans per lokalem OCR) wird nur in vault.db gespeichert.

* Nutzt die Extraktion und das OCR von anonymizer-core (``anonymizer.documents``, ``anonymizer.ocr``).
* Arca verlangt standardmäßig Netzwerk-Isolation für OCR (``ARCA_OCR_ISOLATION=require``): ohne
  ``unshare --net`` wird kein Scan gelesen. In Docker (kein unshare) wird ``auto`` gesetzt; dann ist die
  Netzwerkkonfiguration des Containers die Grenze.
* Gespeichert werden Text, Dateiname, Format und SHA-256, nicht die Originaldatei (Datenminimierung).
* Der Text erscheint in Spalte "Dokumente" (Freitext) und geht nur über Vorschau und Freigabe nach A.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time

from anonymizer.documents import DocumentError, Extracted, extract_docx, extract_image, extract_pdf, sniff
from anonymizer.ocr import OCRError, TesseractOCR

MAX_BYTES = 25 * 1024 * 1024
CONFIGURED = object()  # Standard: lokales OCR mit Pflicht-Isolation; None = kein OCR


class UploadError(ValueError):
    pass


def ocr_engine() -> TesseractOCR | None:
    try:
        engine = TesseractOCR(isolation=os.environ.get("ARCA_OCR_ISOLATION") or "require")
    except OCRError:
        return None
    return engine if engine.available() else None


def add_document(conn: sqlite3.Connection, mandat_id: int, filename: str, data: bytes,
                 engine=CONFIGURED) -> dict:
    if not conn.execute("SELECT 1 FROM mandate WHERE id = ?", (mandat_id,)).fetchone():
        raise UploadError("Mandat nicht gefunden")
    if not data or len(data) > MAX_BYTES:
        raise UploadError("Datei leer oder größer als 25 MB")
    engine = ocr_engine() if engine is CONFIGURED else engine
    try:
        fmt = sniff(data, filename)
        if fmt == "pdf":
            extracted = extract_pdf(data, ocr=engine)
        elif fmt == "image":
            extracted = extract_image(data, ocr=engine)
        elif fmt == "docx":
            extracted = extract_docx(data)
        else:
            extracted = Extracted("text", data.decode("utf-8"))
    except DocumentError as exc:
        raise UploadError(f"Dokument nicht lesbar: {exc}") from exc
    if any("OCR required" in w for w in extracted.warnings):
        raise UploadError("Scan ohne Textebene, aber kein lokales OCR mit Netzwerk-Isolation verfügbar")
    text = extracted.text.replace("\f", "\n\n").strip()
    if not text:
        raise UploadError("Kein Text erkannt")
    ocr = any("OCR" in w for w in extracted.warnings)
    doc = {"mandat_id": mandat_id, "dateiname": filename[:200], "sha256": hashlib.sha256(data).hexdigest(),
           "format": extracted.format, "ocr": ocr, "chars": len(text), "warnings": extracted.warnings,
           "notes": extracted.notes}
    conn.execute("INSERT INTO dokumente (mandat_id, dateiname, sha256, format, ocr, text, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (mandat_id, doc["dateiname"], doc["sha256"], doc["format"], int(ocr), text, time.time()))
    conn.commit()
    return doc
