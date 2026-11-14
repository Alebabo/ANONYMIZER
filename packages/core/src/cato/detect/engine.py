"""Detection engine: runs recognizers, resolves overlaps, links mentions."""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel, Field

from cato.detect.base import Recognizer, supports
from cato.detect.context import find_signals, signals_near
from cato.detect.ner import NERUnavailable, SpacyRecognizer
from cato.detect.recognizers import NAME_STOPWORDS, builtin_recognizers, custom_recognizer
from cato.models import Category, Detection, EntityType as E, ScanResult, Suppressed, make_detection

# Higher rank wins an overlap. Validated checksums beat everything; custom
# entity types rank high because users define them deliberately.
SPECIFICITY: dict[str, int] = {
    E.IBAN: 100, E.CREDIT_CARD: 95, E.EMAIL: 95, E.TAX_ID: 90, E.SOCIAL_SECURITY_NUMBER: 90,
    E.VAT_ID: 85, E.BIC: 85, E.TAX_NUMBER: 85, E.CASE_NUMBER: 80, E.DATE_OF_BIRTH: 78, E.ADDRESS: 75,
    E.LEGAL_CITATION: 72, E.ORGANIZATION: 70, E.PERSON: 65, E.COURT: 60, E.PHONE: 55, E.MONEY: 50,
    E.DATE: 45, E.HEALTH_DATA: 40, E.BIOMETRIC_DATA: 40, E.SPECIAL_CATEGORY: 40, E.CRIMINAL_RECORD: 40,
    E.PRIVILEGE_MARKER: 30, E.BUSINESS_SECRET_MARKER: 30, E.LOCATION: 20,
}
CUSTOM_RANK = 88

# Entity types whose text is a value (name, address, ...). Context words
# inside such values are not document cues.
VALUE_TYPES = {E.EMAIL, E.ADDRESS, E.ORGANIZATION, E.PERSON, E.LOCATION}

_STOP_DE = {"der", "die", "das", "und", "ist", "nicht", "mit", "von", "den", "dem", "ein", "eine", "wir", "sie",
            "zu", "auf", "für", "im", "des", "wird", "wurde", "sehr", "geehrte", "unser", "bei", "aus", "auch"}
_STOP_EN = {"the", "and", "is", "of", "to", "in", "that", "with", "for", "our", "we", "this", "on", "are",
            "was", "be", "by", "an", "has", "have", "dear", "from", "which", "not", "at", "as"}


def detect_language(text: str) -> str:
    words = re.findall(r"[a-zäöüß]+", text.lower())
    de = sum(w in _STOP_DE for w in words)
    en = sum(w in _STOP_EN for w in words)
    if de == en:
        return "unknown"
    return "de" if de > en else "en"


class DetectorConfig(BaseModel):
    min_confidence: float = Field(0.3, ge=0.0, le=1.0)
    context_window: int = Field(150, ge=0)
    enable_ner: bool = False
    ner_models: dict[str, str] | None = None
    custom_entities: list[dict] = Field(default_factory=list)
    disabled_recognizers: list[str] = Field(default_factory=list)


class Detector:
    def __init__(self, config: DetectorConfig | None = None, recognizers: list[Recognizer] | None = None) -> None:
        self.config = config or DetectorConfig()
        base = recognizers if recognizers is not None else builtin_recognizers()
        base = [r for r in base if r.name not in self.config.disabled_recognizers]
        base += [custom_recognizer(spec) for spec in self.config.custom_entities]
        self._ner = SpacyRecognizer(self.config.ner_models) if self.config.enable_ner else None
        self.recognizers: list[Recognizer] = base

    # ------------------------------------------------------------------
    def scan(self, text: str, language: str | None = None) -> ScanResult:
        lang = language or detect_language(text)
        warnings: list[str] = []
        candidates: list[Detection] = []
        for recognizer in self.recognizers:
            if supports(recognizer, lang):
                candidates.extend(recognizer.analyze(text, lang))
        if self._ner is not None:
            try:
                candidates.extend(self._ner.analyze(text, lang))
            except NERUnavailable as exc:
                warnings.append(f"NER disabled: {exc}")

        accepted, _ = resolve_overlaps(candidates)
        candidates.extend(propagate_mentions(text, accepted))
        accepted, suppressed = resolve_overlaps(candidates)
        accepted = assign_refs(accepted)

        # Cues inside a detected span (e.g. "example" in an e-mail domain)
        # describe the value, not the document.
        values = [d for d in accepted if d.entity_type in VALUE_TYPES]
        signals = [s for s in find_signals(text)
                   if not any(d.start <= s.start and s.end <= d.end for d in values)]
        final: list[Detection] = []
        for det in accepted:
            det = det.model_copy(update={
                "signals": signals_near(text, signals, det.start, det.end, self.config.context_window),
            })
            if det.confidence < self.config.min_confidence:
                suppressed.append(Suppressed(detection=det, overlapped_by="", reason="below_min_confidence"))
                continue
            final.append(det)
        return ScanResult(language=lang, detections=final, suppressed=suppressed, signals=signals, warnings=warnings)


# ----------------------------------------------------------------------
def _rank(det: Detection) -> tuple:
    rank = SPECIFICITY.get(det.entity_type, CUSTOM_RANK if det.recognizer.startswith("custom:") else 0)
    return (det.validated is True, rank, det.end - det.start, det.confidence)


def resolve_overlaps(candidates: list[Detection]) -> tuple[list[Detection], list[Suppressed]]:
    """Greedy, deterministic: best-ranked span wins, losers are reported."""
    # Collapse identical spans of the same type (several recognizers agree).
    unique: dict[tuple[str, int, int], Detection] = {}
    for det in candidates:
        key = (det.entity_type, det.start, det.end)
        if key not in unique or _rank(det) > _rank(unique[key]):
            unique[key] = det
    ordered = sorted(unique.values(), key=lambda d: (_rank(d), -d.start), reverse=True)
    accepted: list[Detection] = []
    suppressed: list[Suppressed] = []
    for det in ordered:
        blocker = next((a for a in accepted if det.start < a.end and a.start < det.end), None)
        if blocker is None:
            accepted.append(det)
        else:
            suppressed.append(Suppressed(detection=det, overlapped_by=blocker.id, reason="overlap"))
    accepted.sort(key=lambda d: d.start)
    return accepted, suppressed


def _surname(name: str) -> str | None:
    last = name.split(" ")[-1]
    if len(last) < 3 or last in NAME_STOPWORDS:
        return None
    return last


def propagate_mentions(text: str, accepted: list[Detection]) -> list[Detection]:
    """Find further mentions of already detected persons.

    "Max Mustermann ... Herr Mustermann ... Mustermann" -> all three are
    marked. Surnames are only propagated when they are unambiguous in the
    document (two different people called Mustermann -> no surname matches).
    """
    persons = [d for d in accepted if d.entity_type == E.PERSON]
    full_names = {d.text for d in persons if " " in d.text}
    surname_owners: dict[str, set[str]] = defaultdict(set)
    for name in full_names:
        if (s := _surname(name)) is not None:
            surname_owners[s].add(name)
    roles = {d.text: d.attributes.get("role") for d in persons if d.attributes.get("role")}

    out: list[Detection] = []
    targets: dict[str, float] = {name: 0.8 for name in full_names}
    for surname, owners in surname_owners.items():
        if len(owners) == 1:
            targets.setdefault(surname, 0.7)
            if (owner := next(iter(owners))) in roles:
                roles.setdefault(surname, roles[owner])
    for d in persons:  # single-token anchors such as "Herr Mustermann"
        if " " not in d.text and _surname(d.text):
            targets.setdefault(d.text, 0.7)
    for value, confidence in targets.items():
        for m in re.finditer(rf"(?<![\w-]){re.escape(value)}(?![\w-])", text):
            attrs = {"role": roles[value]} if value in roles else {}
            out.append(make_detection(E.PERSON, Category.PERSONAL_DATA, m.start(), m.end(), value, confidence,
                                      "person_propagation", attributes=attrs))
    return out


def assign_refs(detections: list[Detection]) -> list[Detection]:
    """Attach opaque, document-local reference ids (``person_1``) that group
    mentions of the same entity. Used for consistent pseudonymization. The
    ref is never derived from the raw value."""
    persons = [d for d in detections if d.entity_type == E.PERSON]
    full = [d.text for d in persons if " " in d.text]
    by_surname: dict[str, set[str]] = defaultdict(set)
    for name in full:
        if (s := _surname(name)) is not None:
            by_surname[s].add(name)

    def canonical(det: Detection) -> str:
        if det.entity_type == E.PERSON and " " not in det.text and len(by_surname.get(det.text, ())) == 1:
            return next(iter(by_surname[det.text]))
        return det.text

    counters: dict[str, int] = defaultdict(int)
    refs: dict[tuple[str, str], str] = {}
    out: list[Detection] = []
    for det in detections:
        if det.entity_type not in (E.PERSON, E.ORGANIZATION):
            out.append(det)
            continue
        key = (det.entity_type, canonical(det))
        if key not in refs:
            counters[det.entity_type] += 1
            refs[key] = f"{det.entity_type}_{counters[det.entity_type]}"
        out.append(det.model_copy(update={"attributes": {**det.attributes, "ref": refs[key]}}))
    # Propagate roles across all mentions of the same ref.
    role_by_ref = {d.attributes["ref"]: d.attributes["role"] for d in out if "ref" in d.attributes and "role" in d.attributes}
    return [
        d.model_copy(update={"attributes": {**d.attributes, "role": role_by_ref[d.attributes["ref"]]}})
        if d.attributes.get("ref") in role_by_ref and "role" not in d.attributes else d
        for d in out
    ]
