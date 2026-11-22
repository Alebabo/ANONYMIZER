"""Optional second statistical detector: GLiNER (zero-shot span NER).

Off by default. Enable with ``ANONYMIZER_GLINER_MODEL`` (Hugging Face id or local path, e.g.
``urchade/gliner_multi-v2.1``) or ``DetectorConfig(gliner_model=...)``; needs the optional dependency
``pip install "anonymizer-core[gliner]"``. Without the package the engine records a warning and continues
exactly as before. Measurements and the recommendation: ``docs/research/gliner-results.md``.

GLiNER spans go through the same filters as spaCy spans (``authority_type``, ``clean_entity`` with the NER
stopwords) and rank below rules and below spaCy on any overlap (``engine._rank``): courts, statutes and
citations found by the rules always win, and spaCy keeps its own spans. GLiNER only adds spans nobody else found.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from typing import Any

from anonymizer.detect.ner import _LABELS, NERUnavailable, authority_type, clean_entity
from anonymizer.models import Detection, EntityType as E, make_detection

# Prompt labels per entity type. GLiNER is prompted in English (its training language), also for German text.
PROMPTS: dict[str, tuple[str, ...]] = {
    E.PERSON: ("person",),
    E.ORGANIZATION: ("organization", "company"),
    E.LOCATION: ("location",),
}
_TYPE_NAMES = {"person": E.PERSON, "per": E.PERSON, "organization": E.ORGANIZATION, "org": E.ORGANIZATION,
               "location": E.LOCATION, "loc": E.LOCATION}
DEFAULT_TYPES = "organization"
DEFAULT_THRESHOLD = 0.5
# GLiNER models are trained on 384-word windows; longer inputs are truncated. Chunks end at sentence ends.
_CHUNK_WORDS = 200
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+(?=[A-ZÄÖÜ„\"(§])|\n+")

_MODEL_CACHE: dict[str, Any] = {}


def parse_types(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """'organization' / 'PER,ORG,LOC' -> entity types; unknown names are ignored."""
    names = value.split(",") if isinstance(value, str) else list(value or [])
    out = [_TYPE_NAMES[n.strip().lower()] for n in names if n.strip().lower() in _TYPE_NAMES]
    return tuple(dict.fromkeys(out))


def chunks(text: str, max_words: int = _CHUNK_WORDS) -> list[tuple[int, str]]:
    """(offset, chunk) pieces of at most ``max_words`` words, cut at sentence ends where possible."""
    pieces: list[tuple[int, int]] = []
    pos = 0
    for m in _SENTENCE_END.finditer(text):
        pieces.append((pos, m.start()))
        pos = m.end()
    pieces.append((pos, len(text)))
    out: list[tuple[int, str]] = []
    cur_start, cur_end, cur_words = None, 0, 0
    for s, e in pieces:
        words = len(text[s:e].split())
        if not words:
            continue
        if words > max_words:  # one very long "sentence": cut at whitespace
            if cur_start is not None:
                out.append((cur_start, text[cur_start:cur_end]))
                cur_start, cur_words = None, 0
            spans = [m.span() for m in re.finditer(r"\S+", text[s:e])]
            for i in range(0, len(spans), max_words):
                part = spans[i:i + max_words]
                out.append((s + part[0][0], text[s + part[0][0]:s + part[-1][1]]))
            continue
        if cur_start is not None and cur_words + words > max_words:
            out.append((cur_start, text[cur_start:cur_end]))
            cur_start, cur_words = None, 0
        if cur_start is None:
            cur_start = s
        cur_end, cur_words = e, cur_words + words
    if cur_start is not None:
        out.append((cur_start, text[cur_start:cur_end]))
    return out


def _load(model: str) -> Any:
    if model not in _MODEL_CACHE:
        try:
            from gliner import GLiNER  # noqa: PLC0415
        except ImportError as exc:
            raise NERUnavailable('GLiNER is not installed (pip install "anonymizer-core[gliner]")') from exc
        try:
            _MODEL_CACHE[model] = GLiNER.from_pretrained(model)
        except Exception as exc:  # noqa: BLE001 - download, file or format errors
            raise NERUnavailable(f"GLiNER model '{model}' could not be loaded: {exc}") from exc
    return _MODEL_CACHE[model]


class GlinerRecognizer:
    name = "gliner"
    languages: frozenset[str] = frozenset()  # multilingual

    def __init__(self, model: str, types: Iterable[str] = (E.ORGANIZATION,), threshold: float = DEFAULT_THRESHOLD,
                 stopwords: set[str] | None = None, batch_size: int = 8) -> None:
        self.model = model
        self.types = tuple(types)
        self.threshold = threshold
        self.stopwords = stopwords or set()
        self.batch_size = batch_size
        # All types are prompted, also when only some are kept: a "person" label competing with "company"
        # keeps surnames from being returned as companies.
        self.prompts = {p: t for t, ps in PROMPTS.items() for p in ps}

    def predict(self, pieces: list[str]) -> list[list[dict[str, Any]]]:
        """Raw GLiNER output per piece: dicts with start, end, label, score (offsets within the piece)."""
        return _load(self.model).inference(pieces, list(self.prompts), threshold=self.threshold, flat_ner=True,
                                           batch_size=self.batch_size)

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        if not self.types or not text.strip():
            return
        parts = chunks(text)
        for (offset, _), preds in zip(parts, self.predict([p for _, p in parts])):
            for p in preds:
                if p["score"] < self.threshold or p["label"] not in self.prompts:
                    continue
                entity_type = self.prompts[p["label"]]
                start = offset + p["start"]
                value = text[start:offset + p["end"]]
                entity_type, value = authority_type(value, entity_type)
                if entity_type not in self.types:  # a "location" that is a court: courts are left to the rules
                    continue
                cleaned = clean_entity(value, start, entity_type, self.stopwords)
                if cleaned is None:
                    continue
                start, value = cleaned
                _, category, confidence = _LABELS[{E.PERSON: "PER", E.ORGANIZATION: "ORG"}.get(entity_type, "LOC")]
                yield make_detection(entity_type, category, start, start + len(value), value, confidence, self.name,
                                     attributes={"score": f"{p['score']:.2f}", "label": p["label"]})


def from_env() -> dict[str, Any]:
    """DetectorConfig defaults from ANONYMIZER_GLINER_MODEL / _TYPES / _THRESHOLD."""
    return {
        "gliner_model": os.environ.get("ANONYMIZER_GLINER_MODEL") or None,
        "gliner_types": os.environ.get("ANONYMIZER_GLINER_TYPES") or DEFAULT_TYPES,
        "gliner_threshold": float(os.environ.get("ANONYMIZER_GLINER_THRESHOLD") or DEFAULT_THRESHOLD),
    }
