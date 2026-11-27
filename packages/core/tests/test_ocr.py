"""Local OCR: scanned PDFs and images become text; strictly offline; OCR pages go to review."""

from __future__ import annotations

import io
import socket
import subprocess

import pytest

from anonymizer import documents
from anonymizer.ocr import OCRError, TesseractOCR, _from_tsv, _unshare_works, default_engine

PIL = pytest.importorskip("PIL")
pytest.importorskip("pypdfium2")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ENGINE = TesseractOCR(isolation="auto")
needs_ocr = pytest.mark.skipif(not ENGINE.available(), reason="tesseract with German data not installed")

LETTER = [
    "Sehr geehrte Frau Schneider,",
    "unser Mandant Max Mustermann, Geschäftsführer der Muster GmbH,",
    "fordert die Rückzahlung des Darlehens über 500.000 Euro.",
    "Aktenzeichen 3 O 123/24, Landgericht Hamburg.",
]


def scan_image(lines=LETTER) -> Image.Image:
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    img = Image.new("L", (1700, 120 + 70 * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((80, 60 + 70 * i), line, fill=0, font=font)
    return img


def as_bytes(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **({"resolution": 200.0} if fmt == "PDF" else {}))
    return buf.getvalue()


@pytest.fixture()
def no_network(monkeypatch):
    """Any attempt of this process to open a connection fails the test."""
    def refuse(*a, **k):
        raise AssertionError("network access during OCR")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@needs_ocr
def test_scanned_pdf_is_read(no_network):
    extracted = documents.extract(as_bytes(scan_image(), "PDF"), "brief.pdf")
    assert extracted.format == "pdf"
    assert "Mustermann" in extracted.text and "Muster GmbH" in extracted.text
    assert any("OCR" in w for w in extracted.warnings)  # degrades -> review
    assert extracted.notes and "locally" in extracted.notes[0]


@needs_ocr
@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "TIFF"])
def test_images(no_network, fmt):
    extracted = documents.extract(as_bytes(scan_image(), fmt))
    assert extracted.format == "image" and "Schneider" in extracted.text
    assert extracted.warnings


@needs_ocr
def test_protect_scanned_pdf_end_to_end(no_network):
    from anonymizer.pipeline import Pipeline
    from anonymizer.policy import builtin_policy

    scan = as_bytes(scan_image(), "PDF")
    result = documents.protect_document(Pipeline(policy=builtin_policy("legal-default")), scan, "brief.pdf")
    assert result.allowed
    text = result.content.decode()
    for name in ("Mustermann", "Schneider", "Muster GmbH", "3 O 123/24"):
        assert name not in text
    assert any("OCR" in w for w in result.warnings)
    # Policies that review uncertain documents hold OCR results back (fail closed).
    held = documents.protect_document(Pipeline(policy=builtin_policy("banking-default")), scan, "brief.pdf")
    assert not held.allowed and held.content is None


def test_without_ocr_scan_stays_unreadable():
    extracted = documents.extract_pdf(as_bytes(scan_image(), "PDF"), ocr=None)
    assert any("OCR required" in w for w in extracted.warnings)
    with pytest.raises(documents.DocumentError):
        documents.extract_image(as_bytes(scan_image(), "PNG"), ocr=None)


def test_off_switch(monkeypatch):
    monkeypatch.setenv("ANONYMIZER_OCR", "off")
    assert default_engine() is None


def test_command_uses_stdin_only_and_isolation():
    cmd = TesseractOCR(isolation="auto", binary="/usr/bin/tesseract").command()
    i = cmd.index("/usr/bin/tesseract")
    assert cmd[i + 1:i + 3] == ["stdin", "stdout"]  # never a path or URL
    if _unshare_works():
        assert cmd[:3] == [cmd[0], "--net", "--map-root-user"]
    off = TesseractOCR(isolation="off", binary="/usr/bin/tesseract").command()
    assert off[0] == "/usr/bin/tesseract"


def test_env_has_no_proxy_or_secrets(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
    monkeypatch.setenv("ANONYMIZER_VAULT_KEY", "secret")
    env = TesseractOCR()._env()
    assert "HTTPS_PROXY" not in env and "ANONYMIZER_VAULT_KEY" not in env


@pytest.mark.skipif(not _unshare_works(), reason="no unprivileged network namespaces")
def test_isolated_namespace_has_no_network():
    """The sandbox OCR runs in cannot reach anything: only a downed loopback, no route."""
    probe = ("import socket\n"
             "try:\n socket.create_connection(('1.1.1.1', 443), timeout=3); print('online')\n"
             "except OSError: print('offline')")
    out = subprocess.run(["unshare", "--net", "--map-root-user", "python3", "-c", probe],
                         capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "offline"


def test_require_isolation_refuses_without_unshare(monkeypatch):
    monkeypatch.setattr("anonymizer.ocr._unshare_works", lambda: False)
    engine = TesseractOCR(isolation="require", binary="/usr/bin/tesseract")
    assert not engine.available()
    with pytest.raises(OCRError):
        engine.command()


def test_invalid_language_rejected():
    with pytest.raises(OCRError):
        TesseractOCR(lang="deu; rm -rf /")


def test_tsv_parsing():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\tMax\n5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t80\tMustermann\n"
           "5\t1\t1\t1\t2\t1\t0\t0\t1\t1\t70\tHamburg\n5\t1\t2\t1\t1\t1\t0\t0\t1\t1\t-1\tNeu\n")
    page = _from_tsv(tsv, True)
    assert page.text == "Max Mustermann\nHamburg\n\nNeu"
    assert page.confidence == 80.0
