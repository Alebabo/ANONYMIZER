"""Optional spaCy NER recognizer (``pip install cato-core[ner]``).

Models are loaded lazily and must be installed separately, e.g.
``python -m spacy download de_core_news_lg``. If spaCy or a model is
missing, the engine records a warning and continues with rule-based
detection only.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cato.models import Category, Detection, EntityType as E, make_detection

DEFAULT_MODELS = {"de": "de_core_news_lg", "en": "en_core_web_lg"}

_LABELS = {
    "PER": (E.PERSON, Category.PERSONAL_DATA, 0.8),
    "PERSON": (E.PERSON, Category.PERSONAL_DATA, 0.8),
    "ORG": (E.ORGANIZATION, Category.PERSONAL_DATA, 0.6),
    "LOC": (E.LOCATION, Category.PERSONAL_DATA, 0.5),
    "GPE": (E.LOCATION, Category.PERSONAL_DATA, 0.5),
}


class NERUnavailable(RuntimeError):
    pass


class SpacyRecognizer:
    name = "spacy_ner"

    def __init__(self, models: dict[str, str] | None = None) -> None:
        self.models = models or DEFAULT_MODELS
        self.languages = frozenset(self.models)
        self._loaded: dict[str, Any] = {}

    def _nlp(self, language: str) -> Any:
        if language not in self._loaded:
            try:
                import spacy  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise NERUnavailable("spaCy is not installed (pip install cato-core[ner])") from exc
            try:
                self._loaded[language] = spacy.load(self.models[language], disable=["parser", "lemmatizer"])
            except OSError as exc:  # pragma: no cover
                raise NERUnavailable(f"spaCy model '{self.models[language]}' is not installed") from exc
        return self._loaded[language]

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        languages = [language] if language in self.models else list(self.models)
        for lang in languages:
            doc = self._nlp(lang)(text)
            for ent in doc.ents:
                mapped = _LABELS.get(ent.label_)
                if mapped is None:
                    continue
                entity_type, category, confidence = mapped
                yield make_detection(entity_type, category, ent.start_char, ent.end_char, ent.text,
                                     confidence, self.name)
