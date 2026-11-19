"""Document formats: TXT/MD, DOCX (anonymized in place) and PDF (text only).

Security notes
* Inputs are untrusted. Uploads are size-limited, the format is checked by
  magic bytes (not by file name) and DOCX archives are checked against
  zip bombs before parsing.
* DOCX: runs are rewritten in place so formatting survives. Document
  properties (author, last modified by, title, ...) are cleared. Comments,
  tracked changes and embedded objects cannot be anonymized reliably; their
  presence is reported as a warning, which makes the classification
  degraded (never "low") and puts the document into review.
* PDF: only the text layer is extracted; the result is anonymized plain
  text, not a redacted PDF. Pages without a text layer (scans) are reported:
  OCR is not part of OpenAnonymizer yet, so such documents must not be treated as
  clean.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Literal

from anonymizer.anonymize import OpenAnonymizer
from anonymizer.detect import Detector
from anonymizer.models import ScanResult

Format = Literal["text", "docx", "pdf"]

MAX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
PARAGRAPH_SEP = "\n\n"


class DocumentError(ValueError):
    pass


def sniff(data: bytes, filename: str | None = None) -> Format:
    """Detect the format from content; the file name is only a tie-breaker."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile as exc:
            raise DocumentError("corrupt zip container") from exc
        raise DocumentError("zip container is not a DOCX document")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentError("unsupported format (expected PDF, DOCX or UTF-8 text)") from exc
    if filename and filename.lower().endswith((".pdf", ".docx")):
        raise DocumentError("file content does not match its extension")
    return "text"


@dataclass
class Extracted:
    format: Format
    text: str
    warnings: list[str] = field(default_factory=list)  # degrade the scan -> review
    pages: int | None = None
    notes: list[str] = field(default_factory=list)     # informational only


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def extract_pdf(data: bytes, min_chars_per_page: int = 20) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentError("encrypted PDFs are not supported")
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise DocumentError("unreadable PDF") from exc
    warnings = []
    empty = [i + 1 for i, p in enumerate(pages) if len(p.strip()) < min_chars_per_page]
    if empty:
        warnings.append(f"pages without text layer (scan? OCR required): {_ranges(empty)}")
    text = "\f".join(_clean_pdf_text(p) for p in pages)  # \f = page break
    return Extracted("pdf", text, warnings, pages=len(pages))


def _clean_pdf_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # hyphenation at line end
    return text


def _ranges(nums: list[int]) -> str:
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:] + [None]:  # type: ignore[list-item]
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        if n is not None:
            start = prev = n
    return ", ".join(out)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def _check_zip(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        total = sum(i.file_size for i in z.infolist())
        if total > MAX_UNCOMPRESSED or (len(data) and total / len(data) > MAX_COMPRESSION_RATIO):
            raise DocumentError("DOCX archive is suspiciously large when uncompressed (zip bomb?)")


def _docx_paragraphs(doc):
    """All paragraphs incl. tables, headers and footers, in document order."""
    def from_container(container):
        for p in container.paragraphs:
            yield p
        for table in getattr(container, "tables", []):
            for row in table.rows:
                for cell in row.cells:
                    yield from from_container(cell)

    yield from from_container(doc)
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            if part is not None and not part.is_linked_to_previous:
                yield from from_container(part)


def _docx_warnings(data: bytes) -> list[str]:
    warnings = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        body = z.read("word/document.xml")
        if "word/comments.xml" in names:
            warnings.append("document contains comments (not anonymized)")
        if b"<w:ins " in body or b"<w:del " in body:
            warnings.append("document contains tracked changes (not anonymized)")
        if any(n.startswith("word/embeddings/") for n in names):
            warnings.append("document contains embedded objects (not anonymized)")
    return warnings


def _docx_notes(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if any(n.startswith("word/media/") for n in z.namelist()):
            return ["document contains images; they are kept unchanged and were not inspected"]
    return []


def _unique_paragraphs(doc) -> list:
    seen, out = set(), []
    for p in _docx_paragraphs(doc):
        key = id(p._p)
        if key not in seen:  # merged table cells repeat paragraphs
            seen.add(key)
            out.append(p)
    return out


def extract_docx(data: bytes) -> Extracted:
    import docx

    _check_zip(data)
    doc = docx.Document(io.BytesIO(data))
    text = PARAGRAPH_SEP.join(p.text for p in _unique_paragraphs(doc))
    return Extracted("docx", text, _docx_warnings(data), notes=_docx_notes(data))


def anonymize_docx(data: bytes, transformations: list) -> bytes:
    """Apply transformations (offsets in the extracted text) to the DOCX runs."""
    import docx

    _check_zip(data)
    doc = docx.Document(io.BytesIO(data))
    paragraphs = _unique_paragraphs(doc)
    # paragraph start offsets in the joined text
    starts, pos = [], 0
    for p in paragraphs:
        starts.append(pos)
        pos += len(p.text) + len(PARAGRAPH_SEP)

    per_para: dict[int, list] = {}
    for t in transformations:
        idx = max(i for i, s in enumerate(starts) if s <= t.start)
        local_start, local_end = t.start - starts[idx], t.end - starts[idx]
        if local_end > len(paragraphs[idx].text):
            raise DocumentError("transformation crosses a paragraph boundary")
        per_para.setdefault(idx, []).append((local_start, local_end, t.replacement))

    for idx, edits in per_para.items():
        _rewrite_runs(paragraphs[idx], sorted(edits, reverse=True))

    props = doc.core_properties
    for attr in ("author", "last_modified_by", "title", "subject", "keywords", "comments", "category"):
        setattr(props, attr, "")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _rewrite_runs(paragraph, edits_desc: list[tuple[int, int, str]]) -> None:
    """Replace [start, end) in the paragraph text, touching runs minimally.

    The replacement goes into the run where the span starts; the rest of the
    span is cut from the following runs. Formatting of untouched text stays.
    Text outside runs (e.g. inside hyperlinks/fields) falls back to a
    paragraph-level rewrite so nothing is left behind.
    """
    runs = list(paragraph.runs)
    if "".join(r.text for r in runs) != paragraph.text:
        # Text lives partly outside plain runs (hyperlinks, fields): rebuild
        # the paragraph as one run. Loses inline formatting of this paragraph
        # only, but guarantees no original text is left behind.
        new = paragraph.text
        for s, e, rep in edits_desc:
            new = new[:s] + rep + new[e:]
        style_source = runs[0] if runs else None
        for child in list(paragraph._p):
            if child.tag.split("}")[-1] in ("r", "hyperlink", "fldSimple", "smartTag", "sdt"):
                paragraph._p.remove(child)
        run = paragraph.add_run(new)
        if style_source is not None:
            run.bold, run.italic, run.underline = style_source.bold, style_source.italic, style_source.underline
        return
    for s, e, rep in edits_desc:
        offset = 0
        first = True
        for run in runs:
            r_start, r_end = offset, offset + len(run.text)
            offset = r_end
            if r_end <= s or r_start >= e:
                continue
            a, b = max(s, r_start) - r_start, min(e, r_end) - r_start
            if first:
                run.text = run.text[:a] + rep + run.text[b:]
                first = False
                # later runs' offsets shift; recompute by restarting
            else:
                run.text = run.text[:a] + run.text[b:]
        # runs changed length; nothing else to do because edits run back to front


# ---------------------------------------------------------------------------
# High level
# ---------------------------------------------------------------------------

def extract(data: bytes, filename: str | None = None) -> Extracted:
    fmt = sniff(data, filename)
    if fmt == "pdf":
        return extract_pdf(data)
    if fmt == "docx":
        return extract_docx(data)
    return Extracted("text", data.decode("utf-8"))


def with_document_warnings(scan: ScanResult, extracted: Extracted) -> ScanResult:
    """Document warnings degrade the scan, so classification never says 'low'."""
    if not extracted.warnings:
        return scan
    return scan.model_copy(update={"warnings": [*scan.warnings, *extracted.warnings]})


def scan_document(detector: Detector, extracted: Extracted, language: str | None = None) -> ScanResult:
    return with_document_warnings(detector.scan(extracted.text, language), extracted)


class DocumentResult:
    """Outcome of :func:`protect_document`. ``content`` is the anonymized
    file (DOCX) or UTF-8 text (TXT/PDF); ``None`` if sending is not allowed."""

    def __init__(self, extracted: Extracted, result, content: bytes | None, media_type: str | None) -> None:
        self.format = extracted.format
        self.pages = extracted.pages
        self.warnings = extracted.warnings
        self.notes = extracted.notes
        self.result = result
        self.content = content
        self.media_type = media_type

    @property
    def allowed(self) -> bool:
        return self.content is not None


DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def protect_document(pipeline, data: bytes, filename: str | None = None, destination: str = "external",
                     namespace: str | None = None, language: str | None = None,
                     max_bytes: int = 25 * 1024 * 1024) -> DocumentResult:
    """Extract, detect, classify, apply policy and anonymize a document."""
    if len(data) > max_bytes:
        raise DocumentError(f"document exceeds {max_bytes} bytes")
    extracted = extract(data, filename)
    if not extracted.text.strip():
        raise DocumentError("document contains no extractable text (scan? OCR required)")
    scan = scan_document(pipeline.detector, extracted, language)
    result = pipeline.protect_scan(extracted.text, scan, destination, namespace)
    if not result.allowed:
        return DocumentResult(extracted, result, None, None)
    if extracted.format != "docx":
        return DocumentResult(extracted, result, result.text.encode("utf-8"), "text/plain; charset=utf-8")
    transformations = result.anonymization.transformations
    out = anonymize_docx(data, transformations)
    # Independent check on the produced file: no transformed value may remain.
    final = extract_docx(out).text.casefold()
    leftovers = []
    for t in transformations:
        original = extracted.text[t.start:t.end]
        if len(original) >= 3 and original != t.replacement and original.casefold() in final:
            leftovers.append(t.detection_id)
    if leftovers:
        from anonymizer.anonymize import LeakError
        raise LeakError(f"{len(leftovers)} value(s) still present in the anonymized DOCX")
    return DocumentResult(extracted, result, out, DOCX_MEDIA)


__all__ = [
    "DocumentResult", "protect_document",
    "DocumentError", "Extracted", "anonymize_docx", "extract", "extract_docx", "extract_pdf", "scan_document",
    "sniff", "with_document_warnings", "OpenAnonymizer",
]
