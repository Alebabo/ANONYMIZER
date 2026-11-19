"""Classification engine: risk per entity and per document, with reasons.

Rule order per entity (each step is recorded as a reason):

1. base risk of the entity type
2. procedural role (client, accused, ...)        -> can only raise
3. context signal rules                          -> can only raise
   + link rules (person near special-category data) -> can only raise
4. example context                               -> may lower one level
5. configured overrides                          -> set
6. manual corrections                            -> set
7. confidence below review threshold             -> needs_review (never lowers)

Uncertainty is never resolved towards "less sensitive".
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import Counter

from pydantic import BaseModel, Field

from anonymizer.classify.config import ClassifierConfig, Override, RiskLevel
from anonymizer.models import Detection, ScanResult


class Reason(BaseModel):
    code: str
    message: str


class EntityClassification(BaseModel):
    """Classification of one detection. Contains no raw value."""

    detection_id: str
    entity_type: str
    category: str
    start: int
    end: int
    confidence: float
    base_risk: RiskLevel
    risk: RiskLevel
    needs_review: bool
    reasons: list[Reason]
    attributes: dict[str, str] = Field(default_factory=dict)


class DocumentClassification(BaseModel):
    language: str
    risk: RiskLevel
    confidence: float
    needs_review: bool
    counts: dict[RiskLevel, int]
    entities: list[EntityClassification]
    reasons: list[Reason]
    signals: list[str]
    warnings: list[str] = Field(default_factory=list)

    @property
    def level(self) -> int:
        return self.risk.level


def _override_matches(o: Override, d: Detection) -> bool:
    return ((o.entity_type is None or o.entity_type == d.entity_type)
            and (o.category is None or o.category == d.category.value)
            and (o.recognizer is None or o.recognizer == d.recognizer))


class Classifier:
    def __init__(self, config: ClassifierConfig | None = None) -> None:
        self.config = config or ClassifierConfig()

    def classify_text(self, text: str, scan: ScanResult,
                      corrections: dict[str, RiskLevel] | None = None) -> DocumentClassification:
        breaks = [m.start() for m in re.finditer(r"\n\s*\n", text)]
        return self.classify(scan, corrections, breaks)

    # ------------------------------------------------------------------
    def classify_entity(
        self, det: Detection, document_signals: set[str], correction: RiskLevel | None = None,
        linked: dict[str, set[str]] | None = None,
    ) -> EntityClassification:
        cfg = self.config
        reasons: list[Reason] = []

        base = cfg.base_risk.get(det.entity_type, cfg.unknown_type_risk)
        risk = base
        reasons.append(Reason(code=f"base:{det.entity_type}",
                              message=f"Entity type '{det.entity_type}' is {base.value} by default."))

        role = det.attributes.get("role")
        if role and (role_risk := cfg.role_risk.get(role)) and role_risk > risk:
            risk = role_risk
            reasons.append(Reason(code=f"role:{role}", message=f"Person appears as '{role}', raised to {risk.value}."))

        near = set(det.signals)
        for rule in cfg.signal_rules:
            if det.entity_type not in rule.entity_types:
                continue
            pool = document_signals if rule.scope == "document" else near
            hit = sorted(set(rule.signals) & pool)
            if hit and rule.min_risk > risk:
                risk = rule.min_risk
                reasons.append(Reason(code=f"signal:{rule.name}",
                                      message=f"Context {', '.join(hit)} raises to {risk.value}."))

        for rule_name, min_risk in self._link_hits(det, linked or {}):
            if min_risk > risk:
                risk = min_risk
                reasons.append(Reason(code=f"link:{rule_name}",
                                      message=f"Linked to nearby {rule_name.replace('_', ' ')} data, raised to {risk.value}."))

        if (cfg.example_lowering and "example_context" in near and det.entity_type in cfg.example_lowerable
                and det.validated is not True and risk > RiskLevel.LOW):
            blockers = sorted(set(cfg.example_blockers) & (near | document_signals))
            if blockers:
                reasons.append(Reason(code="example:blocked",
                                      message=f"Example context ignored because of {', '.join(blockers)}."))
            else:
                risk = risk.lower()
                reasons.append(Reason(code="example:lowered",
                                      message=f"Example/fictitious context lowers to {risk.value}."))

        for o in cfg.overrides:
            if _override_matches(o, det):
                risk = o.risk
                reasons.append(Reason(code="override", message=f"{o.reason}: set to {risk.value}."))

        if correction is not None:
            risk = correction
            reasons.append(Reason(code="manual", message=f"Manually corrected to {risk.value}."))

        needs_review = det.validated is False or (det.confidence < cfg.review_threshold and risk >= RiskLevel.SENSITIVE)
        if needs_review:
            reasons.append(Reason(code="review:low_confidence",
                                  message=f"Confidence {det.confidence:.2f} below {cfg.review_threshold:.2f}"
                                          + (" or checksum failed" if det.validated is False else "") + "."))

        return EntityClassification(
            detection_id=det.id, entity_type=det.entity_type, category=det.category.value,
            start=det.start, end=det.end, confidence=det.confidence, base_risk=base, risk=risk,
            needs_review=needs_review, reasons=reasons,
            attributes={k: v for k, v in det.attributes.items() if k in ("role", "ref", "subtype")},
        )

    def _link_hits(self, det: Detection, linked: dict[str, set[str]]) -> list[tuple[str, RiskLevel]]:
        return [(rule.name, rule.min_risk) for rule in self.config.link_rules if rule.name in linked.get(det.id, set())]

    def _links(self, scan: ScanResult, text_breaks: list[int]) -> dict[str, set[str]]:
        """detection id -> names of link rules that apply to it."""
        out: dict[str, set[str]] = {}
        breaks = sorted(text_breaks)
        for rule in self.config.link_rules:
            # Detections are non-overlapping, so sorting by start also sorts by end
            # and the targets within ``window`` form one contiguous slice.
            targets = sorted((d for d in scan.detections if d.category.value in rule.linked_categories),
                             key=lambda d: d.start)
            starts = [t.start for t in targets]
            ends = [t.end for t in targets]
            for det in scan.detections:
                if det.entity_type not in rule.entity_types:
                    continue
                first = bisect_left(ends, det.start - rule.window)
                last = bisect_right(starts, det.end + rule.window)
                for t in targets[first:last]:
                    lo, hi = min(det.start, t.start), max(det.end, t.end)
                    i = bisect_right(breaks, lo)
                    if i == len(breaks) or breaks[i] >= hi:  # no paragraph break in between
                        out.setdefault(det.id, set()).add(rule.name)
                        break
        return out

    # ------------------------------------------------------------------
    def classify(
        self, scan: ScanResult, corrections: dict[str, RiskLevel] | None = None,
        paragraph_breaks: list[int] | None = None,
    ) -> DocumentClassification:
        """Classify a scan result.

        ``paragraph_breaks`` (offsets of blank lines) limits link rules to a
        paragraph; use :meth:`classify_text` to have it computed.
        """
        corrections = corrections or {}
        doc_signals = scan.document_signals
        linked = self._links(scan, paragraph_breaks or [])
        entities = [self.classify_entity(d, doc_signals, corrections.get(d.id), linked) for d in scan.detections]
        counts = Counter(e.risk for e in entities)
        reasons: list[Reason] = []

        if entities:
            risk = max(e.risk for e in entities)
            drivers = [e for e in entities if e.risk == risk]
            confidence = max(e.confidence for e in drivers)
            kinds = sorted({e.entity_type for e in drivers})
            reasons.append(Reason(code="document:max",
                                  message=f"Highest entity risk {risk.value} ({', '.join(kinds)})."))
        else:
            risk, confidence = RiskLevel.LOW, 1.0
            reasons.append(Reason(code="document:empty", message="No sensitive entities detected."))

        if risk < RiskLevel.SENSITIVE and counts[RiskLevel.SENSITIVE] >= self.config.document_sensitive_count:
            risk = RiskLevel.SENSITIVE

        needs_review = any(e.needs_review for e in entities)
        if scan.warnings:
            # Degraded detection (e.g. NER missing): a 'low' result is not trustworthy.
            needs_review = True
            if risk == RiskLevel.LOW:
                risk = RiskLevel.SENSITIVE
                reasons.append(Reason(code="document:degraded",
                                      message="Detection ran in degraded mode; raised to sensitive."))
            reasons.append(Reason(code="document:warnings", message="; ".join(scan.warnings)))

        return DocumentClassification(
            language=scan.language, risk=risk, confidence=round(confidence, 4), needs_review=needs_review,
            counts={lvl: counts.get(lvl, 0) for lvl in RiskLevel}, entities=entities, reasons=reasons,
            signals=sorted(doc_signals), warnings=list(scan.warnings),
        )
