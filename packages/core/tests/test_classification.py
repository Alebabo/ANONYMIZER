import json

import pytest

from anonymizer import scan
from anonymizer.classify import Classifier, ClassifierConfig, Override, RiskLevel, SignalRule
from anonymizer.models import Category, ScanResult, make_detection

L, S, C = RiskLevel.LOW, RiskLevel.SENSITIVE, RiskLevel.CRITICAL
CLS = Classifier()


def classify(text, language="de", **kw):
    return CLS.classify_text(text, scan(text, language), **kw)


def risk_of(doc, entity_type, index=0):
    return [e for e in doc.entities if e.entity_type == entity_type][index]


def codes(entity):
    return [r.code for r in entity.reasons]


# --- risk levels -----------------------------------------------------------

def test_risk_level_ordering():
    assert L < S < C and C.level == 3 and C.lower() == S and L.lower() == L
    assert max([S, C, L]) == C


# --- spec example ------------------------------------------------------------

def test_spec_example_vs_client_in_criminal_proceeding():
    example = classify("Beispiel: Herr Max Mustermann ist ein fiktiver Name in diesem Musterformular.")
    client = classify("Herr Max Mustermann ist unser Mandant im laufenden Strafverfahren.")
    assert risk_of(example, "person").risk == L
    assert "example:lowered" in codes(risk_of(example, "person"))
    assert risk_of(client, "person").risk == C
    assert client.risk == C


def test_example_lowering_blocked_by_conflicting_context():
    doc = classify("Beispiel: Herr Max Mustermann ist unser Mandant im Strafverfahren.")
    person = risk_of(doc, "person")
    assert person.risk == C and "example:blocked" in codes(person)


def test_example_never_lowers_validated_identifiers_or_special_categories():
    doc = classify("Beispiel: IBAN DE89 3704 0044 0532 0130 00, Diagnose Depression.")
    assert risk_of(doc, "iban").risk == C
    assert risk_of(doc, "health_data").risk == C


# --- rules -------------------------------------------------------------------

def test_role_raises_person():
    doc = classify("Der Beschuldigte Herr Tim Beispiel schweigt.")
    assert risk_of(doc, "person").risk == C and "role:accused" in codes(risk_of(doc, "person"))


def test_person_linked_to_health_data_is_critical():
    doc = classify("The plaintiff, Laura Kingsley, was diagnosed with cancer.\n\nRobert Hale will testify.", "en")
    kingsley = next(e for e in doc.entities if e.entity_type == "person" and e.start < 30)
    assert kingsley.risk == C and "link:data_subject_of_special_category" in codes(kingsley)


def test_link_rule_does_not_cross_paragraphs():
    doc = classify("Herr Max Mustermann wohnt in Köln.\n\nDie Diagnose lautet Depression.")
    assert risk_of(doc, "person").risk == S


def test_salary_is_sensitive_in_employment_context():
    doc = classify("Das Bruttogehalt beträgt 4.850,00 EUR.")
    assert risk_of(doc, "money").risk == S


def test_public_references_stay_low():
    doc = classify("Gemäß § 823 Abs. 1 BGB hat der Bundesgerichtshof entschieden.")
    assert {e.risk for e in doc.entities} == {L}
    assert doc.risk == L


# --- confidence and review -----------------------------------------------------

def _scan(*dets, warnings=()):
    return ScanResult(language="de", detections=list(dets), warnings=list(warnings))


def test_low_confidence_sensitive_entity_needs_review_but_is_not_lowered():
    det = make_detection("person", Category.PERSONAL_DATA, 0, 5, "Xaver", 0.4, "t")
    doc = CLS.classify(_scan(det))
    assert doc.entities[0].risk == S and doc.entities[0].needs_review and doc.needs_review


def test_low_confidence_low_risk_entity_does_not_force_review():
    det = make_detection("location", Category.PERSONAL_DATA, 0, 4, "Köln", 0.45, "spacy_ner")
    assert not CLS.classify(_scan(det)).needs_review


def test_failed_checksum_needs_review():
    det = make_detection("iban", Category.FINANCIAL_DATA, 0, 22, "DE00...", 0.5, "iban", validated=False)
    doc = CLS.classify(_scan(det))
    assert doc.entities[0].risk == C and doc.needs_review


def test_degraded_detection_cannot_produce_low_document():
    doc = CLS.classify(_scan(warnings=["NER disabled: spaCy model missing"]))
    assert doc.risk == S and doc.needs_review


def test_empty_document_is_low():
    doc = CLS.classify(_scan())
    assert doc.risk == L and not doc.needs_review


# --- configuration -------------------------------------------------------------

def test_thresholds_configurable():
    det = make_detection("person", Category.PERSONAL_DATA, 0, 5, "Xaver", 0.7, "t")
    strict = Classifier(ClassifierConfig(review_threshold=0.9))
    assert strict.classify(_scan(det)).needs_review
    assert not CLS.classify(_scan(det)).needs_review


def test_base_risk_override_merges_with_defaults():
    cfg = ClassifierConfig(base_risk={"organization": "critical"})
    assert cfg.base_risk["organization"] == C
    assert cfg.base_risk["iban"] == C  # defaults kept


def test_policy_override():
    cfg = ClassifierConfig(overrides=[Override(entity_type="email", risk=C, reason="Team policy")])
    doc = Classifier(cfg).classify_text("Mail: a@b.de", scan("Mail: a@b.de"))
    assert risk_of(doc, "email").risk == C and "override" in codes(risk_of(doc, "email"))


def test_custom_signal_rule():
    cfg = ClassifierConfig(signal_rules=[SignalRule(name="all_dates", signals=["litigation"],
                                                    entity_types=["date"], min_risk=C)])
    text = "Die Klage wurde am 03.04.2024 eingereicht."
    assert risk_of(Classifier(cfg).classify_text(text, scan(text)), "date").risk == C


def test_manual_correction_is_applied_and_audited():
    text = "Gemäß § 823 Abs. 1 BGB"
    result = scan(text)
    det_id = result.detections[0].id
    doc = CLS.classify(result, corrections={det_id: C})
    assert doc.entities[0].risk == C and codes(doc.entities[0])[-1] == "manual"


def test_config_from_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("review_threshold: 0.8\nbase_risk:\n  date: sensitive\n", encoding="utf-8")
    cfg = ClassifierConfig.from_yaml(p)
    assert cfg.review_threshold == 0.8 and cfg.base_risk["date"] == S


def test_unknown_custom_type_defaults_to_sensitive():
    det = make_detection("client_number", Category.LEGAL_DATA, 0, 10, "MDT-004711", 0.9, "custom:client_number")
    assert CLS.classify(_scan(det)).entities[0].risk == S


# --- guarantees ------------------------------------------------------------------

def test_every_entity_has_reasons_and_no_raw_values():
    text = "Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00, Diagnose Depression."
    doc = classify(text)
    assert all(e.reasons for e in doc.entities)
    dump = json.dumps(doc.model_dump(mode="json"))
    for secret in ("Mustermann", "DE89", "Depression"):
        assert secret not in dump


@pytest.mark.parametrize("text", [
    "Herr Max Mustermann ist unser Mandant im laufenden Strafverfahren 123 Js 4567/24.",
    "The plaintiff, Laura Kingsley, was diagnosed with cancer.",
])
def test_classification_is_deterministic(text):
    a = classify(text).model_dump(mode="json")
    b = classify(text).model_dump(mode="json")
    assert a == b
