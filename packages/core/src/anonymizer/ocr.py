"""Local OCR for scanned PDFs and images (Tesseract, German by default). Strictly offline.

Why it is built this way (professional secrecy, § 203 StGB):

* No cloud service, no model download at runtime. Tesseract is a local binary; the language data
  (``deu.traineddata``) is installed with it (``apt-get install tesseract-ocr tesseract-ocr-deu``).
* Images go to Tesseract through stdin and the text comes back through stdout: no temporary files with
  client content on disk, and never a path or URL argument (Tesseract builds with libcurl would otherwise
  fetch ``http(s)://`` inputs).
* Network isolation: Tesseract runs in its own empty network namespace (``unshare --net``, Linux) where
  no interface but a downed loopback exists. ``ANONYMIZER_OCR_ISOLATION``:
  ``auto`` (default: isolate when the system allows it), ``require`` (refuse OCR without isolation),
  ``off``.
* Minimal environment for the subprocess (no proxy variables, no keys), fixed timeout.
* OCR text can contain recognition errors ("Mustermarm"), which detection may miss. Callers therefore
  mark OCR pages as a document warning: the classification is degraded and the document goes to review.

Configuration: ``ANONYMIZER_OCR`` = ``auto`` (default: on when Tesseract is installed) | ``off``;
``ANONYMIZER_OCR_LANG`` (default ``deu``; e.g. ``deu+eng``); ``ANONYMIZER_OCR_DPI`` (default 300).
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

ISOLATION_MODES = ("auto", "require", "off")
_SAFE_ENV = ("PATH", "LANG", "LC_ALL", "TESSDATA_PREFIX")


class OCRError(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRPage:
    text: str
    confidence: float | None  # mean word confidence 0-100, None if no words
    isolated: bool            # ran without network access


@lru_cache(maxsize=1)
def _unshare_works() -> bool:
    exe = shutil.which("unshare")
    if exe is None:
        return False
    try:
        return subprocess.run([exe, "--net", "--map-root-user", "true"], capture_output=True,
                              timeout=10, env={"PATH": os.environ.get("PATH", "")}).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class TesseractOCR:
    def __init__(self, lang: str | None = None, dpi: int | None = None, isolation: str | None = None,
                 timeout: float = 120.0, binary: str | None = None) -> None:
        self.lang = lang or os.environ.get("ANONYMIZER_OCR_LANG") or "deu"
        self.dpi = dpi or int(os.environ.get("ANONYMIZER_OCR_DPI") or 300)
        self.isolation = isolation or os.environ.get("ANONYMIZER_OCR_ISOLATION") or "auto"
        if self.isolation not in ISOLATION_MODES:
            raise OCRError(f"ANONYMIZER_OCR_ISOLATION must be one of {', '.join(ISOLATION_MODES)}")
        if not all(part.isalpha() and part.isascii() for part in self.lang.split("+")):
            raise OCRError("invalid OCR language")
        self.timeout = timeout
        self.binary = binary or shutil.which("tesseract")

    # -- availability -----------------------------------------------------
    def available(self) -> bool:
        if self.binary is None:
            return False
        if self.isolation == "require" and not _unshare_works():
            return False
        return set(self.lang.split("+")) <= self.languages()

    def languages(self) -> set[str]:
        if self.binary is None:
            return set()
        out = subprocess.run([self.binary, "--list-langs"], capture_output=True, text=True,
                             timeout=30, env=self._env())
        return {line.strip() for line in out.stdout.splitlines()[1:] if line.strip()}

    @property
    def isolated(self) -> bool:
        return self.isolation != "off" and _unshare_works()

    # -- recognition --------------------------------------------------------
    def _env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ}
        env["OMP_THREAD_LIMIT"] = "1"
        return env

    def command(self) -> list[str]:
        cmd = [self.binary or "tesseract", "stdin", "stdout", "-l", self.lang, "--dpi", str(self.dpi),
               "--psm", "3", "tsv"]
        if self.isolated:
            cmd = [shutil.which("unshare") or "unshare", "--net", "--map-root-user", *cmd]
        elif self.isolation == "require":
            raise OCRError("network isolation required but unavailable (unshare --net)")
        return cmd

    def image(self, data: bytes) -> OCRPage:
        """Recognize one image (PNG, JPEG, TIFF ...). Content goes in via stdin only."""
        if not self.available():
            raise OCRError("OCR unavailable (install tesseract-ocr and tesseract-ocr-deu)")
        try:
            out = subprocess.run(self.command(), input=data, capture_output=True, timeout=self.timeout,
                                 env=self._env())
        except subprocess.TimeoutExpired as exc:
            raise OCRError("OCR timed out") from exc
        if out.returncode != 0:
            raise OCRError("OCR failed")  # stderr may echo content; never forward it
        return _from_tsv(out.stdout.decode("utf-8", "replace"), self.isolated)

    def pdf_pages(self, data: bytes, pages: list[int]) -> dict[int, OCRPage]:
        """Render the given 1-based PDF pages locally (pdfium) and recognize them."""
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(data)
        try:
            result = {}
            for number in pages:
                bitmap = doc[number - 1].render(scale=self.dpi / 72)
                buf = io.BytesIO()
                bitmap.to_pil().convert("L").save(buf, format="PNG")
                result[number] = self.image(buf.getvalue())
            return result
        finally:
            doc.close()


def _from_tsv(tsv: str, isolated: bool) -> OCRPage:
    """Rebuild lines and paragraphs from Tesseract's TSV and average the word confidences."""
    lines: dict[tuple, list[str]] = {}
    confidences: list[float] = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        word = (row.get("text") or "").strip()
        if row.get("level") != "5" or not word:
            continue
        key = (int(row["page_num"]), int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        lines.setdefault(key, []).append(word)
        try:
            if float(row["conf"]) >= 0:
                confidences.append(float(row["conf"]))
        except (TypeError, ValueError):
            pass
    parts: list[str] = []
    previous = None
    for key in sorted(lines):
        if previous is not None:
            parts.append("\n\n" if key[:3] != previous[:3] else "\n")
        parts.append(" ".join(lines[key]))
        previous = key
    return OCRPage("".join(parts), sum(confidences) / len(confidences) if confidences else None, isolated)


def default_engine() -> TesseractOCR | None:
    """The configured engine, or None if OCR is switched off or not installed."""
    if (os.environ.get("ANONYMIZER_OCR") or "auto").lower() == "off":
        return None
    try:
        engine = TesseractOCR()
    except OCRError:
        return None
    return engine if engine.available() else None
