"""Corpus evaluation: recall on labelled entities, documented FP/FN, and
unlabelled extra detections for manual review.

Corpus format (YAML, one document per file)::

    id: de_example
    language: de
    text: |
      ...
    expected:              # must be detected (type + exact text, optional role)
      - {type: person, text: Max Mustermann, role: client, risk: critical}
      - {type: person, text: Robert Hale, requires: ner}  # skipped without NER
    must_not_detect:       # type and/or text; any match is a false positive
      - {type: tax_id, text: "12345678901"}
    expected_risk: critical  # document-level classification
    expected_signals: [criminal_proceeding]
    absent_signals: [example_context]
    known_false_negatives: # documented misses; must currently be missed
      - {type: person, text: Robert Hale, note: "..."}
    known_false_positives: # documented wrong hits; must currently be hit
      - {type: person, text: Ober, note: "..."}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from cato.classify import Classifier, DocumentClassification
from cato.detect import Detector
from cato.models import Detection, ScanResult


@dataclass
class DocReport:
    id: str
    result: ScanResult
    classification: DocumentClassification | None = None
    wrong_document_risk: tuple[str, str] | None = None
    wrong_risk: list[tuple[dict, str]] = field(default_factory=list)
    missed: list[dict] = field(default_factory=list)
    wrong_role: list[tuple[dict, Detection]] = field(default_factory=list)
    false_positives: list[tuple[dict, Detection]] = field(default_factory=list)
    missing_signals: list[str] = field(default_factory=list)
    unexpected_signals: list[str] = field(default_factory=list)
    fixed_false_negatives: list[dict] = field(default_factory=list)
    fixed_false_positives: list[dict] = field(default_factory=list)
    unlabelled: list[Detection] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # require NER, which is unavailable
    expected_count: int = 0
    known_fn_count: int = 0
    known_fp_count: int = 0

    @property
    def ok(self) -> bool:
        return not (self.missed or self.wrong_role or self.wrong_risk or self.wrong_document_risk or self.false_positives or self.missing_signals
                    or self.unexpected_signals or self.fixed_false_negatives or self.fixed_false_positives)


def load_corpus(directory: Path) -> list[dict]:
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.yaml"))]


def _matches(spec: dict, det: Detection) -> bool:
    return (spec.get("type") in (None, det.entity_type)) and (spec.get("text") in (None, det.text))


def evaluate_doc(doc: dict, detector: Detector, classifier: Classifier | None = None) -> DocReport:
    result = detector.scan(doc["text"], doc.get("language"))
    classification = (classifier or Classifier()).classify_text(doc["text"], result)
    risk_by_id = {e.detection_id: e.risk.value for e in classification.entities}
    report = DocReport(id=doc["id"], result=result, expected_count=len(doc.get("expected", [])),
                       known_fn_count=len(doc.get("known_false_negatives", [])),
                       known_fp_count=len(doc.get("known_false_positives", [])))
    report.classification = classification
    if (want := doc.get("expected_risk")) and want != classification.risk.value:
        report.wrong_document_risk = (want, classification.risk.value)
    dets = result.detections
    matched: set[str] = set()
    ner_active = detector.config.enable_ner and not any("NER disabled" in w for w in result.warnings)

    for spec in doc.get("expected", []):
        if spec.get("requires") == "ner" and not ner_active:
            report.skipped.append(spec)
            continue
        hits = [d for d in dets if _matches(spec, d)]
        if not hits:
            report.missed.append(spec)
            continue
        matched.update(d.id for d in hits)
        if "role" in spec:
            for d in hits:
                if d.attributes.get("role") != spec["role"]:
                    report.wrong_role.append((spec, d))
        if "risk" in spec:
            for d in hits:
                if risk_by_id[d.id] != spec["risk"]:
                    report.wrong_risk.append((spec, risk_by_id[d.id]))

    for spec in doc.get("must_not_detect", []):
        report.false_positives += [(spec, d) for d in dets if _matches(spec, d)]

    signals = result.document_signals
    report.missing_signals = [s for s in doc.get("expected_signals", []) if s not in signals]
    report.unexpected_signals = [s for s in doc.get("absent_signals", []) if s in signals]

    for spec in doc.get("known_false_negatives", []):
        if any(_matches(spec, d) for d in dets):
            report.fixed_false_negatives.append(spec)
    for spec in doc.get("known_false_positives", []):
        hits = [d for d in dets if _matches(spec, d)]
        if not hits:
            report.fixed_false_positives.append(spec)
        matched.update(d.id for d in hits)

    report.unlabelled = [d for d in dets if d.id not in matched]
    return report


def summarize(reports: list[DocReport]) -> dict:
    expected = sum(r.expected_count - len(r.skipped) for r in reports)
    missed = sum(len(r.missed) for r in reports)
    known_fn = sum(r.known_fn_count for r in reports)
    fps = sum(len(r.false_positives) for r in reports)
    found = expected - missed
    return {
        "documents": len(reports),
        "expected_entities": expected + known_fn,
        "recall": round(found / (expected + known_fn), 4) if expected + known_fn else None,
        "false_positive_hits": fps,
        "documented_false_negatives": known_fn,
        "documented_false_positives": sum(r.known_fp_count for r in reports),
        "unlabelled_detections": sum(len(r.unlabelled) for r in reports),
        "skipped_requires_ner": sum(len(r.skipped) for r in reports),
    }
