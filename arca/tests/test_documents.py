"""Scans per lokalem OCR in vault.db; nach Freigabe kein Originalname aus dem Scan in visible.db."""

from __future__ import annotations

import io
import socket
import sqlite3

import pytest

from arca import vault_db
from arca.documents import UploadError, add_document, ocr_engine
from arca.release import release

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

needs_ocr = pytest.mark.skipif(ocr_engine() is None, reason="kein Tesseract mit Netzwerk-Isolation")

LETTER = [
    "Sehr geehrte Frau Schneider,",
    "unser Mandant Max Mustermann, Geschäftsführer der Muster GmbH,",
    "fordert bis zum 30.11.2026 die Rückzahlung des Darlehens.",
    "Ihr Zeuge Peter Lehmann aus Lüneburg hat dies bestätigt.",
]


def scanned_pdf(lines=LETTER) -> bytes:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    img = Image.new("L", (1700, 120 + 70 * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((80, 60 + 70 * i), line, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=200.0)
    return buf.getvalue()


@pytest.fixture()
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("Netzwerkzugriff beim OCR")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@needs_ocr
def test_scan_to_vault_and_release(paths, vault, arca, offline):
    doc = add_document(vault, 1, "Schreiben_Schneider.pdf", scanned_pdf())
    assert doc["ocr"] and doc["format"] == "pdf"
    assert "Mustermann" in vault_db.rows(vault)[0]["dokumente"]
    # Datei selbst wird nicht gespeichert, nur Text und Prüfsumme
    cols = [r[1] for r in vault.execute("PRAGMA table_info(dokumente)")]
    assert "data" not in cols and "sha256" in cols

    preview = arca.preview(["dokumente"])
    cell = preview["rows"][0]["cells"]["dokumente"]["value"]
    assert "PERSON_" in cell and "ORGANIZATION_" in cell
    release(vault, paths[1], preview["id"])
    conn = sqlite3.connect(paths[1])
    blob = "\n".join(str(v) for row in conn.execute("SELECT * FROM mandate") for v in row)
    conn.close()
    for name in ("Schneider", "Mustermann", "Muster GmbH", "Peter", "Lehmann"):
        assert name not in blob, name


@needs_ocr
@pytest.mark.xfail(strict=True, reason="Bekannte Cato-Lücke: Ort nach 'Zeuge ... aus' wird nicht erkannt "
                                       "(nicht OCR-bedingt; 'wohnt in Lüneburg' wird erkannt)")
def test_known_gap_location_in_scan(vault, arca, offline):
    add_document(vault, 1, "brief.pdf", scanned_pdf())
    cell = arca.preview(["dokumente"])["rows"][0]["cells"]["dokumente"]["value"]
    assert "Lüneburg" not in cell


def test_scan_rejected_without_ocr(vault):
    with pytest.raises(UploadError, match="OCR"):
        add_document(vault, 1, "scan.pdf", scanned_pdf(), engine=None)
    assert vault.execute("SELECT COUNT(*) FROM dokumente").fetchone()[0] == 0


def test_arca_requires_network_isolation(monkeypatch):
    monkeypatch.setattr("anonymizer.ocr._unshare_works", lambda: False)
    assert ocr_engine() is None


def test_text_upload_and_errors(vault):
    doc = add_document(vault, 2, "notiz.txt", "Telefonat mit Sabine Keller am Montag.".encode())
    assert not doc["ocr"]
    with pytest.raises(UploadError):
        add_document(vault, 999, "x.txt", b"Hallo")
    with pytest.raises(UploadError):
        add_document(vault, 1, "x.txt", b"")


@needs_ocr
def test_claude_reads_released_documents_via_mcp(paths, vault, arca, offline):
    """Freigegebene Dokumente sind für Claude über MCP vollständig lesbar, nur pseudonymisiert."""
    from test_mcp import srv

    add_document(vault, 1, "brief.pdf", scanned_pdf())
    release(vault, paths[1], arca.preview(["mandant", "dokumente"])["id"])
    db = srv.VisibleDB(paths[1])
    assert db.list_tables() == ["mandate"]
    rows = db.query("SELECT zeile, mandant, dokumente FROM mandate WHERE dokumente != ''")["rows"]
    assert len(rows) == 1 and rows[0][1] in rows[0][2]  # gleiches Token in Spalte und Dokument
    assert "Darlehens" in rows[0][2] and "Mustermann" not in rows[0][2]
