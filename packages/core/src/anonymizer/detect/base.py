"""Recognizer interface and the generic regex recognizer."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from anonymizer.models import DEFAULT_CATEGORIES, Category, Detection, make_detection

LABEL_LOOKBACK = 40


class Recognizer(Protocol):
    name: str
    languages: frozenset[str]  # empty set = language independent

    def analyze(self, text: str, language: str) -> Iterable[Detection]: ...


def supports(recognizer: Recognizer, language: str) -> bool:
    return not recognizer.languages or language == "unknown" or language in recognizer.languages


def has_label_before(text: str, start: int, label: re.Pattern[str] | None, lookback: int = LABEL_LOOKBACK) -> bool:
    """True if a label like 'IBAN:' appears shortly before ``start`` on the same line."""
    if label is None:
        return False
    window = text[max(0, start - lookback):start]
    window = window.rsplit("\n", 1)[-1]
    return label.search(window) is not None


@dataclass(frozen=True)
class Pattern:
    regex: str
    confidence: float
    group: int | str = 0
    flags: int = 0


PostProcess = Callable[[str, int, int], tuple[int, int] | None]


class RegexRecognizer:
    """Pattern-based recognizer with optional validator and label boosting.

    * ``validator`` – called with the matched value. On failure the match is
      dropped (``on_invalid="drop"``) or kept with ``invalid_confidence``
      (``"downgrade"``). A preceding label (``context_words``) always rescues an
      invalid match as a low-confidence detection: unclear data must not pass
      silently. ``checksum=False`` marks a plausibility check only, so
      ``Detection.validated`` stays ``None``.
    * ``context_words`` – regex fragments; when one occurs shortly before the
      match, confidence is raised by ``context_boost``.
    * ``postprocess`` – may shrink or reject a span.
    """

    def __init__(
        self,
        name: str,
        entity_type: str,
        patterns: Sequence[Pattern],
        *,
        category: Category | None = None,
        languages: Iterable[str] = (),
        validator: Callable[[str], bool] | None = None,
        on_invalid: Literal["drop", "downgrade"] = "drop",
        invalid_confidence: float = 0.4,
        context_words: Sequence[str] = (),
        context_boost: float = 0.1,
        postprocess: PostProcess | None = None,
        checksum: bool = True,
        attributes: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.entity_type = str(getattr(entity_type, "value", entity_type))
        self.category = category or DEFAULT_CATEGORIES.get(self.entity_type, Category.PERSONAL_DATA)
        self.languages = frozenset(languages)
        self._patterns = [(re.compile(p.regex, p.flags), p) for p in patterns]
        self._validator = validator
        self._on_invalid = on_invalid
        self._invalid_confidence = invalid_confidence
        self._label = re.compile(r"(?:" + "|".join(context_words) + r")", re.IGNORECASE) if context_words else None
        self._boost = context_boost
        self._postprocess = postprocess
        self._checksum = checksum
        self._attributes = attributes or {}

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        for regex, spec in self._patterns:
            for m in regex.finditer(text):
                start, end = m.span(spec.group)
                if start < 0 or start == end:
                    continue
                if self._postprocess is not None:
                    span = self._postprocess(text, start, end)
                    if span is None:
                        continue
                    start, end = span
                value = text[start:end]
                confidence = spec.confidence
                labeled = has_label_before(text, start, self._label)
                validated: bool | None = None
                if self._validator is not None:
                    ok = self._validator(value)
                    validated = ok if self._checksum else None
                    if not ok:
                        if self._on_invalid == "drop" and not labeled:
                            continue
                        confidence = self._invalid_confidence
                if labeled:
                    confidence = min(0.99, confidence + self._boost)
                yield make_detection(
                    self.entity_type, self.category, start, end, value, confidence,
                    self.name, validated=validated, attributes=dict(self._attributes),
                )


def lexicon(terms: Sequence[str]) -> str:
    """Word-bounded alternation; terms are regex fragments."""
    return r"(?<!\w)(?:" + "|".join(terms) + r")(?!\w)"
