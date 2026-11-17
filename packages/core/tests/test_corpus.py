from pathlib import Path

import pytest

from anonymizer.anonymize import DEFAULT_METHODS, Anonymizer, Method
from anonymizer.detect import Detector
from anonymizer.evaluation import evaluate_doc, load_corpus, summarize

CORPUS = load_corpus(Path(__file__).parent / "corpus")
DETECTOR = Detector()


@pytest.mark.parametrize("doc", CORPUS, ids=[d["id"] for d in CORPUS])
def test_corpus_document(doc):
    r = evaluate_doc(doc, DETECTOR)
    assert not r.missed, f"missed: {r.missed}"
    assert not r.wrong_role, [(s, d.attributes) for s, d in r.wrong_role]
    assert not r.wrong_risk, r.wrong_risk
    assert r.wrong_document_risk is None, f"document risk expected/actual: {r.wrong_document_risk}"
    assert not r.false_positives, [(s, d.entity_type, d.text) for s, d in r.false_positives]
    assert not r.missing_signals, r.missing_signals
    assert not r.unexpected_signals, r.unexpected_signals
    # Documented limitations must stay accurate: if one is fixed, move it to 'expected'.
    assert not r.fixed_false_negatives, f"now detected, move to expected: {r.fixed_false_negatives}"
    assert not r.fixed_false_positives, f"no longer produced, remove: {r.fixed_false_positives}"


def test_corpus_summary_thresholds():
    summary = summarize([evaluate_doc(d, DETECTOR) for d in CORPUS])
    assert summary["false_positive_hits"] == 0
    assert summary["recall"] >= 0.9, summary


@pytest.mark.parametrize("doc", CORPUS, ids=[d["id"] for d in CORPUS])
def test_corpus_anonymization_leaves_no_protected_value(doc):
    result = DETECTOR.scan(doc["text"], doc.get("language"))
    out = Anonymizer().anonymize(doc["text"], result)  # strict: raises on residual values
    for spec in doc.get("expected", []):
        if DEFAULT_METHODS.get(spec["type"], Method.REDACT) != Method.KEEP and len(spec["text"]) >= 3:
            assert spec["text"] not in out.text, spec
