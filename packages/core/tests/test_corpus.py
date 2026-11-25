from pathlib import Path

import pytest

from anonymizer.anonymize import DEFAULT_METHODS, OpenAnonymizer, Method
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
    out = OpenAnonymizer().anonymize(doc["text"], result)  # strict: raises on residual values
    for spec in doc.get("expected", []):
        if DEFAULT_METHODS.get(spec["type"], Method.REDACT) != Method.KEEP and len(spec["text"]) >= 3:
            assert spec["text"] not in out.text, spec


def test_value_inside_kept_value_is_no_leak():
    from anonymizer.models import Category, EntityType, make_detection

    text = "Kläger aus 50667 Köln. Zuständig ist das Arbeitsgericht Köln."
    city = text.index("Köln")
    court = text.index("Arbeitsgericht Köln")
    dets = [make_detection(EntityType.LOCATION, Category.PERSONAL_DATA, city, city + 4, "Köln", 0.8, "test"),
            make_detection(EntityType.COURT, Category.PUBLIC_REFERENCE, court, court + 19, "Arbeitsgericht Köln",
                           0.9, "test")]
    out = OpenAnonymizer().anonymize(text, dets)  # strict
    assert "Arbeitsgericht Köln" in out.text and "50667 Köln" not in out.text
