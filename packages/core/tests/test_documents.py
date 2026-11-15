import base64
import io
import zipfile

import docx
import pytest
from fastapi.testclient import TestClient

from cato.anonymize import LeakError
from cato.api import create_app
from cato.api.settings import Settings
from cato.documents import DocumentError, extract, extract_docx, protect_document, sniff
from cato.mcp import CatoTools, MCPConfig
from cato.pipeline import Pipeline
from cato.policy import Outcome

SECRETS = ["Mustermann", "DE89 3704", "Anna Schmidt"]


def make_pdf(pages: list[str]) -> bytes:
    """Minimal PDF with a Helvetica text layer (ASCII), one text line per entry."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        content = (f"BT /F1 11 Tf 50 750 Td ({text}) Tj ET" if text else "").encode("latin-1")
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode("latin-1").decode("latin-1")
                       + content.decode("latin-1") + "\nendstream")
        content_id = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(comment: bool = False) -> bytes:
    d = docx.Document()
    d.core_properties.author = "RA Dr. Anna Schmidt"
    d.core_properties.title = "Akte Mustermann"
    p = d.add_paragraph("Unser Mandant Herr ")
    bold = p.add_run("Max Mustermann")
    bold.bold = True
    p.add_run(", IBAN DE89 3704 0044 0532 0130 00, bittet um Rückruf.")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Kläger"
    t.cell(0, 1).text = "Herr Max Mustermann"
    d.sections[0].header.paragraphs[0].text = "Kanzlei – Akte Mustermann"
    d.add_paragraph("Mit freundlichen Grüßen, Rechtsanwältin Dr. Anna Schmidt")
    b = io.BytesIO()
    d.save(b)
    data = b.getvalue()
    if comment:  # add a comments part to simulate a commented document
        src = zipfile.ZipFile(io.BytesIO(data))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for item in src.infolist():
                z.writestr(item, src.read(item.filename))
            z.writestr("word/comments.xml", "<w:comments/>")
        data = out.getvalue()
    return data


# --- format detection --------------------------------------------------------------

def test_sniff_by_content_not_name():
    assert sniff(make_pdf(["x"]), "brief.txt") == "pdf"
    assert sniff(make_docx(), "brief.pdf") == "docx"
    assert sniff("Hallo".encode(), "brief.txt") == "text"
    with pytest.raises(DocumentError):
        sniff("Hallo".encode(), "brief.pdf")  # extension lies
    with pytest.raises(DocumentError):
        sniff(b"\x89PNG\r\n\x1a\n\x00\x00", "bild.png")


def test_zip_that_is_not_docx_is_rejected():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(DocumentError, match="not a DOCX"):
        sniff(b.getvalue())


def test_zip_bomb_is_rejected():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("word/padding.xml", "0" * 50_000_000)
    with pytest.raises(DocumentError, match="zip bomb"):
        extract(b.getvalue())


# --- DOCX ---------------------------------------------------------------------------

def test_docx_anonymized_in_place_with_formatting_and_metadata():
    doc = protect_document(Pipeline(), make_docx(), "brief.docx")
    assert doc.allowed and doc.format == "docx" and doc.result.decision.outcome == Outcome.ALLOW
    out = docx.Document(io.BytesIO(doc.content))
    first = out.paragraphs[0]
    assert first.text == "Unser Mandant Herr PERSON_001, IBAN [REDACTED], bittet um Rückruf."
    assert [r.bold for r in first.runs if r.text == "PERSON_001"] == [True]  # formatting kept
    assert out.tables[0].rows[0].cells[1].text == "Herr PERSON_001"
    assert "Mustermann" not in out.sections[0].header.paragraphs[0].text
    assert out.core_properties.author == "" and out.core_properties.title == ""
    full = extract_docx(doc.content).text
    assert not any(s in full for s in SECRETS)


def test_docx_with_comments_goes_to_review():
    doc = protect_document(Pipeline(), make_docx(comment=True), "brief.docx")
    assert not doc.allowed and doc.content is None
    assert doc.result.decision.outcome == Outcome.REVIEW
    assert any("comments" in w for w in doc.warnings)


# --- PDF ----------------------------------------------------------------------------

def test_pdf_text_layer_is_anonymized():
    pdf = make_pdf(["Unser Mandant Herr Max Mustermann bittet um Rueckruf.", "Rueckfragen bitte unter Tel. 030 12345678."])
    doc = protect_document(Pipeline(), pdf, "brief.pdf")
    assert doc.format == "pdf" and doc.pages == 2 and doc.allowed
    text = doc.content.decode()
    assert "PERSON_001" in text and "Mustermann" not in text and "12345678" not in text


def test_pdf_page_without_text_layer_degrades_to_review():
    pdf = make_pdf(["Unser Mandant Herr Max Mustermann bittet um Rueckruf.", ""])
    doc = protect_document(Pipeline(), pdf, "scan.pdf")
    assert any("OCR" in w for w in doc.warnings) and not doc.allowed
    assert doc.result.decision.outcome == Outcome.REVIEW


def test_pdf_without_any_text_is_rejected():
    with pytest.raises(DocumentError, match="no extractable text"):
        protect_document(Pipeline(), make_pdf([""]), "scan.pdf")


def test_size_limit():
    with pytest.raises(DocumentError, match="exceeds"):
        protect_document(Pipeline(), b"a" * 100, "x.txt", max_bytes=10)


# --- API ------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    key = "cato_test_user_key_0123456789abcdef"
    s = Settings.from_env({"CATO_API_KEYS": key, "CATO_POLICY_DIR": str(tmp_path / "p"), "CATO_TRACE_DB": ":memory:",
                           "CATO_MAX_UPLOAD_BYTES": "2000000"})
    return TestClient(create_app(s)), {"Authorization": f"Bearer {key}"}


def test_api_document_upload_docx(client):
    c, h = client
    r = c.post("/v1/documents/protect", headers=h,
               files={"file": ("brief.docx", make_docx(), "application/octet-stream")})
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] and body["format"] == "docx"
    out = docx.Document(io.BytesIO(base64.b64decode(body["content_base64"])))
    assert "PERSON_001" in out.paragraphs[0].text
    assert not any(s in r.text for s in SECRETS)


def test_api_document_upload_rejects_bad_input(client):
    c, h = client
    r = c.post("/v1/documents/protect", headers=h, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422
    r = c.post("/v1/documents/protect", headers=h, files={"file": ("big.txt", b"a" * 2_000_001, "text/plain")})
    assert r.status_code == 413
    assert c.post("/v1/documents/protect", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 401


# --- MCP ------------------------------------------------------------------------------

def test_mcp_reads_docx_and_pdf(tmp_path):
    (tmp_path / "brief.docx").write_bytes(make_docx())
    (tmp_path / "scan.pdf").write_bytes(make_pdf(["Herr Max Mustermann ist unser Mandant.", ""]))
    tools = CatoTools(MCPConfig(root=tmp_path.resolve()))
    r = tools.read_document_protected("brief.docx")
    assert r["allowed"] and r["format"] == "docx" and "PERSON_001" in r["text"]
    assert not any(s in str(r) for s in SECRETS)
    scan = tools.read_document_protected("scan.pdf")
    assert scan["text"] is None and any("OCR" in w for w in scan["document_warnings"])
