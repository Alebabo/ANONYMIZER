"""Optional second statistical detector: newmean-pii (small multilingual PII token classifier, on-device).

Off by default. Enable with ``ANONYMIZER_NEWMEAN_MODEL`` (model size ``nano``, ``small``, ``medium`` or ``large``)
or ``DetectorConfig(newmean_model=...)``; needs the optional dependency ``pip install "anonymizer-core[newmean]"``
(package ``newmean-pii``, Apache-2.0, no further dependencies). Model files are downloaded once from Hugging Face
(``newmean-ai/pii-<size>``) into ``~/.cache/newmean-pii``; for offline use set ``ANONYMIZER_NEWMEAN_MODEL_DIR`` to a
folder with ``tokenizer.web.json`` and ``onnx/model_<variant>.onnx``. Without the package the engine records a
warning and continues exactly as before. Background, links and measurements: ``docs/research/newmean-pii.md``.

Spans rank below rules and below spaCy on any overlap (``engine._rank``), like GLiNER: newmean only adds spans
nobody else found. PERSON and ORG spans go through the same filters as spaCy spans (``authority_type``,
``clean_entity`` with the NER stopwords). Labels without an own OpenAnonymizer type (``ID_NUMBER``, ``FINANCIAL``,
``USERNAME``, ``URL``, ``SECRET``) are kept as lower-case entity types; the policies redact unknown types
(``default_action``).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from anonymizer.detect.ner import NERUnavailable, authority_type, clean_entity
from anonymizer.models import Category, Detection, EntityType as E, make_detection

SIZES = ("nano", "small", "medium", "large")

# newmean label -> (OpenAnonymizer entity type, category, confidence). newmean returns no scores; the confidences
# follow the spaCy values for names and sit above DetectorConfig.min_confidence for everything else.
LABELS: dict[str, tuple[str, Category, float]] = {
    "PERSON": (E.PERSON, Category.PERSONAL_DATA, 0.8),
    "PERSON_L2": (E.PERSON, Category.PERSONAL_DATA, 0.6),
    "ORG": (E.ORGANIZATION, Category.PERSONAL_DATA, 0.6),
    "EMAIL": (E.EMAIL, Category.PERSONAL_DATA, 0.8),
    "PHONE": (E.PHONE, Category.PERSONAL_DATA, 0.7),
    "ADDRESS": (E.ADDRESS, Category.PERSONAL_DATA, 0.7),
    "DATE_OF_BIRTH": (E.DATE_OF_BIRTH, Category.PERSONAL_DATA, 0.7),
    "ID_NUMBER": ("id_number", Category.PERSONAL_DATA, 0.7),
    "FINANCIAL": ("financial", Category.FINANCIAL_DATA, 0.7),
    "USERNAME": ("username", Category.PERSONAL_DATA, 0.6),
    "URL": ("url", Category.PERSONAL_DATA, 0.6),
    "URL_L2": ("url", Category.PERSONAL_DATA, 0.5),
    "SECRET": ("secret", Category.PERSONAL_DATA, 0.7),
}
_NAME_TYPES = (E.PERSON, E.ORGANIZATION)

_MODEL_CACHE: dict[tuple[str, str | None, float, tuple[str, ...]], Any] = {}


def parse_labels(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """'PERSON,ORG' -> newmean labels; empty or 'all' -> every label; unknown names are ignored."""
    names = value.split(",") if isinstance(value, str) else list(value or [])
    out = [n.strip().upper() for n in names if n.strip().upper() in LABELS]
    if not out:
        return tuple(LABELS)
    return tuple(dict.fromkeys(out))


def _load(size: str, model_dir: str | None, sensitivity: float, labels: tuple[str, ...]) -> Any:
    key = (size, model_dir, sensitivity, labels)
    if key not in _MODEL_CACHE:
        if size not in SIZES:
            raise NERUnavailable(f"newmean model size '{size}' is unknown (one of {', '.join(SIZES)})")
        try:
            from newmean_pii import create_redactor  # noqa: PLC0415
        except ImportError as exc:
            raise NERUnavailable('newmean-pii is not installed (pip install "anonymizer-core[newmean]")') from exc
        try:
            _MODEL_CACHE[key] = create_redactor(size=size, sensitivity=sensitivity, labels=list(labels),
                                                model_dir=model_dir)
        except Exception as exc:  # noqa: BLE001 - download, file or checksum errors
            raise NERUnavailable(f"newmean model '{size}' could not be loaded: {exc}") from exc
    return _MODEL_CACHE[key]


class NewmeanRecognizer:
    name = "newmean"
    languages: frozenset[str] = frozenset()  # multilingual

    def __init__(self, size: str, labels: Iterable[str] | None = None, sensitivity: float = 0.0,
                 model_dir: str | None = None, stopwords: set[str] | None = None) -> None:
        self.size = size
        self.labels = parse_labels(labels)
        self.sensitivity = sensitivity
        self.model_dir = model_dir
        self.stopwords = stopwords or set()

    def spans(self, text: str) -> list[Any]:
        """Raw newmean spans (start, end, label, source); offsets are str indices into ``text``."""
        return _load(self.size, self.model_dir, self.sensitivity, self.labels).detect(text)

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        if not text.strip():
            return
        for span in self.spans(text):
            mapped = LABELS.get(span.label)
            if mapped is None:
                continue
            entity_type, category, confidence = mapped
            start, value = span.start, text[span.start:span.end]
            if entity_type in _NAME_TYPES:
                entity_type, value = authority_type(value, entity_type)
                cleaned = clean_entity(value, start, entity_type, self.stopwords)
                if cleaned is None:
                    continue
                start, value = cleaned
            elif not value.strip():
                continue
            yield make_detection(entity_type, category, start, start + len(value), value, confidence, self.name,
                                 attributes={"label": span.label, "model": f"newmean-{self.size}"})


def from_env() -> dict[str, Any]:
    """DetectorConfig defaults from ANONYMIZER_NEWMEAN_MODEL / _LABELS / _SENSITIVITY / _MODEL_DIR."""
    return {
        "newmean_model": (os.environ.get("ANONYMIZER_NEWMEAN_MODEL") or "").strip().lower() or None,
        "newmean_labels": os.environ.get("ANONYMIZER_NEWMEAN_LABELS") or "",
        "newmean_sensitivity": float(os.environ.get("ANONYMIZER_NEWMEAN_SENSITIVITY") or 0.0),
        "newmean_model_dir": os.environ.get("ANONYMIZER_NEWMEAN_MODEL_DIR") or None,
    }
