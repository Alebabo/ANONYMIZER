"""Detection engine: runs recognizers, resolves overlaps, links mentions."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import defaultdict

from pydantic import BaseModel, Field

from anonymizer.detect.base import Recognizer, supports
from anonymizer.detect.context import SignalIndex, find_signals
from anonymizer.detect.ner import NERUnavailable, SpacyRecognizer
from anonymizer.detect.recognizers import NAME_STOPWORDS, builtin_recognizers, custom_recognizer
from anonymizer.models import (
    INNER_WS, Category, Detection, EntityType as E, ScanResult, Signal, Suppressed, make_detection,
)

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
STATISTICAL_RECOGNIZERS = {"spacy_ner"}

# Extra tokens that statistical NER mislabels in legal text.
NER_STOPWORDS = {
    "Az", "Tel", "Fax", "IBAN", "BIC", "NDA", "Mandatsgeheimnis", "Beklagten", "Klägerin", "Zeugin", "Sehr",
    "Geehrte", "Damen", "Herren", "Kündigungsschutzklage", "Rubrum", "Anlage", "Schriftsatz", "Grüßen",
    "PRIVILEGED", "CONFIDENTIAL", "Re", "Dear", "Sincerely",
    # Chat greetings and thanks that German NER labels as names.
    "Danke", "Vielen", "Hallo", "Hi", "Hey", "Moin", "Servus", "Gruß", "Grüße", "LG", "VG", "MfG", "Thanks",
    "Thank", "Hello", "Cheers",
    # Short answers from chat buttons ("Ja", "Nein") that NER labels as places or organisations.
    "Ja", "Nein", "Yes", "No", "Ok", "Okay", "Jein",
}

# Entity types whose text is a value (name, address, ...). Context words
# inside such values are not document cues.
VALUE_TYPES = {E.EMAIL, E.ADDRESS, E.ORGANIZATION, E.PERSON, E.LOCATION}

# Only words that are frequent in one language and rare in the other: "in", "an", "was", "will" are both
# German and English and would tip short German texts towards English.
_STOP_DE = {"der", "die", "das", "und", "ist", "nicht", "mit", "von", "den", "dem", "ein", "eine", "wir", "sie",
            "zu", "auf", "für", "im", "des", "wird", "wurde", "sehr", "geehrte", "unser", "bei", "aus", "auch",
            "ich", "mich", "mir", "mein", "meine", "sein", "seine", "ihr", "ihre", "nach", "zur", "zum", "vom",
            "oder", "aber", "noch", "nur", "schon", "kein", "keine", "bitte", "möchte", "habe", "hat", "sind",
            "über", "wie", "wenn", "dass", "kann", "es", "er"}
_STOP_EN = {"the", "and", "is", "of", "to", "that", "with", "for", "our", "we", "this", "on", "are",
            "be", "by", "has", "have", "dear", "from", "which", "not", "at", "as", "you", "your", "my", "it",
            "please", "would", "can", "there", "what", "been", "were"}


_UMLAUT = re.compile(r"[äöüß]")


def detect_language(text: str) -> str:
    words = re.findall(r"[a-zäöüß]+", text.lower())
    de = sum(w in _STOP_DE or bool(_UMLAUT.search(w)) for w in words)
    en = sum(w in _STOP_EN for w in words)
    if de == en:
        return "unknown"
    return "de" if de > en else "en"


class DetectorConfig(BaseModel):
    min_confidence: float = Field(0.3, ge=0.0, le=1.0)
    context_window: int = Field(150, ge=0)
    enable_ner: bool = True
    ner_models: dict[str, str] | None = None
    custom_entities: list[dict] = Field(default_factory=list)
    disabled_recognizers: list[str] = Field(default_factory=list)
    # Own brands and products ("ACME" keeps "ACME Bank", "ACME Mastercard"): NER spans starting with one of
    # these words are not personal data and stay unchanged. Rule-based detections are not affected.
    keep_terms: list[str] = Field(default_factory=list)


class Detector:
    def __init__(self, config: DetectorConfig | None = None, recognizers: list[Recognizer] | None = None) -> None:
        self.config = config or DetectorConfig()
        base = recognizers if recognizers is not None else builtin_recognizers()
        base = [r for r in base if r.name not in self.config.disabled_recognizers]
        base += [custom_recognizer(spec) for spec in self.config.custom_entities]
        self._ner = (
            SpacyRecognizer(self.config.ner_models, NAME_STOPWORDS | NER_STOPWORDS, keep=self.config.keep_terms)
            if self.config.enable_ner and "spacy_ner" not in self.config.disabled_recognizers else None
        )
        self.recognizers: list[Recognizer] = base

    # ------------------------------------------------------------------
    def prefetch(self, texts: list[str], language: str) -> None:
        """Prepare NER for texts that are about to be scanned one by one (see SpacyRecognizer.prefetch)."""
        if self._ner is not None and texts:
            try:
                self._ner.prefetch(texts, language)
            except NERUnavailable:
                pass  # scan() reports it

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
        values = [d for d in accepted if d.entity_type in VALUE_TYPES]  # sorted, non-overlapping
        value_starts = [d.start for d in values]

        def inside_value(s: Signal) -> bool:
            i = bisect_right(value_starts, s.start)
            return i > 0 and s.end <= values[i - 1].end

        signals = [s for s in find_signals(text) if not inside_value(s)]
        index = SignalIndex(signals)
        final: list[Detection] = []
        for det in accepted:
            det = det.model_copy(update={
                "signals": index.near(text, det.start, det.end, self.config.context_window),
            })
            if det.confidence < self.config.min_confidence:
                suppressed.append(Suppressed(detection=det, overlapped_by="", reason="below_min_confidence"))
                continue
            final.append(det)
        return ScanResult(language=lang, detections=final, suppressed=suppressed, signals=signals, warnings=warnings)


# ----------------------------------------------------------------------
def _rank(det: Detection) -> tuple:
    rank = SPECIFICITY.get(det.entity_type, CUSTOM_RANK if det.recognizer.startswith("custom:") else 0)
    # Deterministic rules beat statistical NER on any overlap.
    return (det.validated is True, det.recognizer not in STATISTICAL_RECOGNIZERS, rank, det.end - det.start,
            det.confidence)


def resolve_overlaps(candidates: list[Detection]) -> tuple[list[Detection], list[Suppressed]]:
    """Greedy, deterministic: best-ranked span wins, losers are reported."""
    # Collapse identical spans of the same type (several recognizers agree).
    unique: dict[tuple[str, int, int], Detection] = {}
    for det in candidates:
        key = (det.entity_type, det.start, det.end)
        if key not in unique or _rank(det) > _rank(unique[key]):
            unique[key] = det
    ordered = sorted(unique.values(), key=lambda d: (_rank(d), -d.start), reverse=True)
    # Accepted spans never overlap, so they are kept sorted by start and an
    # overlap can only involve the neighbours found by bisect.
    starts: list[int] = []
    accepted: list[Detection] = []
    order: dict[str, int] = {}
    suppressed: list[Suppressed] = []
    for det in ordered:
        i = bisect_right(starts, det.start)
        blockers = [accepted[i - 1]] if i and accepted[i - 1].end > det.start else []
        j = i
        while j < len(starts) and starts[j] < det.end:
            blockers.append(accepted[j])
            j += 1
        if not blockers:
            starts.insert(i, det.start)
            accepted.insert(i, det)
            order[det.id] = len(order)
        else:
            blocker = min(blockers, key=lambda a: order[a.id])  # the best-ranked one
            suppressed.append(Suppressed(detection=det, overlapped_by=blocker.id, reason="overlap"))
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
        if " " not in d.text and _surname(d.text) and len(surname_owners.get(d.text, ())) <= 1:
            targets.setdefault(d.text, 0.7)
    for value, confidence in targets.items():
        attrs = {"role": roles[value]} if value in roles else {}
        # Also the spelling used in a rubrum or signature block ("MAX MUSTERMANN").
        # Arbitrary case is not matched: "Weiß" must not hit the verb "weiß".
        variants = [value]
        if (upper := value.upper()) != value and upper.split()[0] in text:
            variants.append(upper)
        for variant in variants:
            pattern = INNER_WS.join(re.escape(token) for token in variant.split())
            for m in re.finditer(rf"(?<![\w-]){pattern}(?![\w-])", text):
                out.append(make_detection(E.PERSON, Category.PERSONAL_DATA, m.start(), m.end(), m.group(0),
                                          confidence, "person_propagation", attributes=attrs))
    return out


def _squash(text: str) -> str:
    return " ".join(text.split())


def assign_refs(detections: list[Detection]) -> list[Detection]:
    """Attach opaque, document-local reference ids (``person_1``) that group
    mentions of the same entity. Used for consistent pseudonymization. The
    ref is never derived from the raw value."""
    persons = [d for d in detections if d.entity_type == E.PERSON]
    # "MAX MUSTERMANN" and "Max\nMustermann" are mentions of "Max Mustermann".
    names = {_squash(d.text) for d in persons}
    names |= {s for n in names if " " in n and (s := _surname(n)) is not None}
    by_upper = {n.upper(): n for n in sorted(names) if n.upper() != n}

    def spelled(det: Detection) -> str:
        name = _squash(det.text)
        return by_upper.get(name, name) if det.entity_type == E.PERSON else name

    by_surname: dict[str, set[str]] = defaultdict(set)
    for name in {spelled(d) for d in persons}:
        if " " in name and (s := _surname(name)) is not None:
            by_surname[s].add(name)

    def canonical(det: Detection) -> str:
        name = spelled(det)
        if det.entity_type == E.PERSON and " " not in name and len(by_surname.get(name, ())) == 1:
            return next(iter(by_surname[name]))
        return name

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
