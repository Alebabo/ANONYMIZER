"""spaCy NER recognizer (enabled by default).

Models are loaded lazily and must be installed separately
(``python -m spacy download de_core_news_lg en_core_web_lg``; the Docker
image ships them). If spaCy or a model is missing, the engine records a
warning and continues with rule-based detection only.

NER results never override rule-based detections (see ``engine._rank``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from cato.models import Category, Detection, EntityType as E, make_detection

DEFAULT_MODELS = {"de": "de_core_news_lg", "en": "en_core_web_lg"}

_LABELS = {
    "PER": (E.PERSON, Category.PERSONAL_DATA, 0.8),
    "PERSON": (E.PERSON, Category.PERSONAL_DATA, 0.8),
    "ORG": (E.ORGANIZATION, Category.PERSONAL_DATA, 0.6),
    "LOC": (E.LOCATION, Category.PERSONAL_DATA, 0.45),
    "GPE": (E.LOCATION, Category.PERSONAL_DATA, 0.45),
}

_LEADING_HONORIFIC = re.compile(r"^(?:(?:Herrn?|Frau|Hr\.|Fr\.|Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)\s+)+")
_CODE_LIKE = re.compile(r"^[A-Z]{1,4}\d*$|\d")


def clean_entity(text: str, start: int, entity_type: str, stopwords: set[str]) -> tuple[int, str] | None:
    """Normalise or reject a raw NER span. Returns (start, text) or None.

    Statistical NER is noisy on legal text: it marks role words
    ("Beklagte"), headings spanning line breaks, abbreviations ("Az", "NDA")
    and code fragments ("DE00") as entities.
    """
    if "\n" in text or "@" in text or "/" in text:
        return None
    m = _LEADING_HONORIFIC.match(text)
    if m:
        start += m.end()
        text = text[m.end():]
    stripped = text.lstrip(" ,.;:()")
    start += len(text) - len(stripped)
    text = stripped.rstrip(" ,.;:()")
    tokens = text.split()
    if len(text) < 3 or not tokens or all(t in stopwords for t in tokens):
        return None
    if entity_type == E.PERSON and any(ch.isdigit() for ch in text):
        return None
    if entity_type != E.LOCATION and _CODE_LIKE.fullmatch(text):
        return None
    if entity_type == E.LOCATION and re.fullmatch(r"[A-Z]{2}\d+|[A-Z][a-z]?", text):
        return None
    return start, text


class NERUnavailable(RuntimeError):
    pass


# Process-wide model cache: loading a large model takes seconds.
_MODEL_CACHE: dict[str, Any] = {}


class SpacyRecognizer:
    name = "spacy_ner"

    def __init__(self, models: dict[str, str] | None = None, stopwords: set[str] | None = None) -> None:
        self.models = models or DEFAULT_MODELS
        self.stopwords = stopwords or set()
        self.languages = frozenset(self.models)

    def _nlp(self, language: str) -> Any:
        model = self.models[language]
        if model not in _MODEL_CACHE:
            try:
                import spacy  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise NERUnavailable("spaCy is not installed") from exc
            try:
                _MODEL_CACHE[model] = spacy.load(model, disable=["parser", "lemmatizer"])
            except OSError as exc:
                raise NERUnavailable(f"spaCy model '{model}' is not installed") from exc
        return _MODEL_CACHE[model]

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        languages = [language] if language in self.models else list(self.models)
        for lang in languages:
            doc = self._nlp(lang)(text)
            for ent in doc.ents:
                mapped = _LABELS.get(ent.label_)
                if mapped is None:
                    continue
                entity_type, category, confidence = mapped
                cleaned = clean_entity(ent.text, ent.start_char, entity_type, self.stopwords)
                if cleaned is None:
                    continue
                start, value = cleaned
                yield make_detection(entity_type, category, start, start + len(value), value,
                                     confidence, self.name)
