import json

import pytest

from anonymizer import scan
from anonymizer.detect import Detector, DetectorConfig, detect_language
from anonymizer.detect import validators as v
from anonymizer.detect.engine import resolve_overlaps
from anonymizer.models import Category, EntityType as E, make_detection


def types(result):
    return [(d.entity_type, d.text) for d in result.detections]


# --- validators ----------------------------------------------------------

@pytest.mark.parametrize("iban,ok", [
    ("DE89 3704 0044 0532 0130 00", True),
    ("DE89370400440532013000", True),
    ("AT611904300234573201", True),
    ("DE89370400440532013001", False),  # checksum
    ("DE8937040044053201300", False),   # length
])
def test_iban(iban, ok):
    assert v.iban_is_valid(iban) is ok


def test_luhn():
    assert v.luhn_is_valid("4111 1111 1111 1111")
    assert not v.luhn_is_valid("4111 1111 1111 1112")


def test_german_tax_id():
    assert v.german_tax_id_is_valid("86095742719")
    assert not v.german_tax_id_is_valid("86095742718")   # check digit
    assert not v.german_tax_id_is_valid("12345678901")   # no repeated digit
    assert not v.german_tax_id_is_valid("06095742719")   # leading zero


# --- recognizers -----------------------------------------------------------

def test_iban_greedy_match_is_trimmed_to_country_length():
    r = scan("IBAN DE89 3704 0044 0532 0130 00 BIC folgt")
    assert ("iban", "DE89 3704 0044 0532 0130 00") in types(r)


def test_invalid_but_labelled_iban_is_kept_with_low_confidence():
    r = scan("Bitte überweisen Sie auf IBAN DE00 1234 5678 9012 3456 78.")
    iban = next(d for d in r.detections if d.entity_type == "iban")
    assert iban.validated is False and iban.confidence <= 0.5


def test_invalid_unlabelled_iban_is_dropped():
    assert not [d for d in scan("Kennung DE00 1234 5678 9012 3456 78").detections if d.entity_type == "iban"]


def test_date_of_birth_requires_label():
    r = scan("geboren am 01.02.1990, Termin am 03.04.2024")
    assert ("date_of_birth", "01.02.1990") in types(r)
    assert ("date", "03.04.2024") in types(r)


def test_invalid_calendar_date_is_ignored():
    assert not [d for d in scan("Version 32.13.2024").detections if d.entity_type == "date"]


def test_person_roles():
    r = scan("Der Beschuldigte Tim Beispiel und die Zeugin Frau Lea Probe wurden geladen.")
    roles = {d.text: d.attributes.get("role") for d in r.detections if d.entity_type == "person"}
    assert roles == {"Tim Beispiel": "accused", "Lea Probe": "witness"}


def test_organization_strips_leading_article():
    assert ("organization", "Muster Handel GmbH") in types(scan("Die Muster Handel GmbH hat geklagt."))


# --- context ---------------------------------------------------------------

def test_spec_example_context_vs_client_context():
    """'Max Mustermann' in an example vs. as a client in criminal proceedings."""
    example = scan("Beispiel: Herr Max Mustermann ist ein fiktiver Name in diesem Musterformular.", "de")
    client = scan("Herr Max Mustermann ist unser Mandant im laufenden Strafverfahren.", "de")
    ex_person = next(d for d in example.detections if d.entity_type == "person")
    cl_person = next(d for d in client.detections if d.entity_type == "person")
    assert "example_context" in ex_person.signals
    assert {"client_relationship", "criminal_proceeding"} <= set(cl_person.signals)
    assert "example_context" not in cl_person.signals


RULES_ONLY = Detector(DetectorConfig(enable_ner=False))


def ner_available() -> bool:
    return not Detector().scan("Herr Max Mustermann", "de").warnings


needs_ner = pytest.mark.skipif(not ner_available(), reason="spaCy models not installed")


def test_bare_name_without_cue_is_missed_in_rules_only_mode():
    r = RULES_ONLY.scan("Max Mustermann ist unser Mandant.", "de")
    assert not [d for d in r.detections if d.entity_type == "person"]


@needs_ner
def test_bare_name_found_by_ner():
    r = scan("Robert Hale will testify. Later, Hale left the room.", "en")
    persons = [d for d in r.detections if d.entity_type == "person"]
    assert [p.text for p in persons] == ["Robert Hale", "Hale"]
    assert len({p.attributes["ref"] for p in persons}) == 1


@needs_ner
def test_ner_never_overrides_rules():
    r = scan("Das OLG Hamm hat entschieden. Streng vertraulich – Mandatsgeheimnis", "de")
    assert ("court", "OLG Hamm") in types(r)
    assert ("privilege_marker", "Mandatsgeheimnis") in types(r)


def test_signal_words_inside_values_are_not_document_signals():
    r = scan("Kontakt: info@example.org")
    assert "example_context" not in r.document_signals


def test_signals_do_not_cross_paragraphs():
    r = scan("Strafverfahren gegen Unbekannt.\n\nHerr Max Mustermann wohnt in Köln.", "de")
    person = next(d for d in r.detections if d.entity_type == "person")
    assert "criminal_proceeding" not in person.signals
    assert "criminal_proceeding" in r.document_signals


# --- mention linking -------------------------------------------------------

def test_mentions_share_ref_and_role():
    r = scan("Unser Mandant Herr Max Mustermann ... Später erschien Mustermann persönlich.", "de")
    persons = [d for d in r.detections if d.entity_type == "person"]
    assert [p.text for p in persons] == ["Max Mustermann", "Mustermann"]
    assert len({p.attributes["ref"] for p in persons}) == 1
    assert all(p.attributes.get("role") == "client" for p in persons)


def test_ambiguous_surname_is_not_propagated():
    text = "Herr Max Mustermann und Frau Erika Mustermann sind verheiratet. Mustermann schweigt."
    r = scan(text, "de")
    persons = [d for d in r.detections if d.entity_type == "person"]
    assert [p.text for p in persons[:2]] == ["Max Mustermann", "Erika Mustermann"]
    refs = [p.attributes["ref"] for p in persons]
    # A bare "Mustermann" may be found by NER, but must not be linked to either person.
    assert len(set(refs)) == len(refs)
    assert not [p for p in persons if p.recognizer == "person_propagation"]


def test_refs_never_contain_raw_values():
    r = scan("Herr Max Mustermann, Muster Handel GmbH", "de")
    for d in r.detections:
        assert "Mustermann" not in d.attributes.get("ref", "")
        assert "Muster" not in d.id


# --- overlap resolution ----------------------------------------------------

def test_overlap_validated_wins_and_loser_is_reported():
    a = make_detection("phone", Category.PERSONAL_DATA, 5, 20, "x" * 15, 0.9, "t")
    b = make_detection("iban", Category.FINANCIAL_DATA, 0, 27, "y" * 27, 0.99, "t", validated=True)
    accepted, suppressed = resolve_overlaps([a, b])
    assert [d.entity_type for d in accepted] == ["iban"]
    assert suppressed[0].detection.entity_type == "phone" and suppressed[0].overlapped_by == b.id


def test_resolution_is_deterministic():
    text = "Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00, Tel. 030 12345678"
    assert scan(text).model_dump() == scan(text).model_dump()


# --- configuration -----------------------------------------------------------

def test_custom_entity_type():
    det = Detector(DetectorConfig(custom_entities=[{
        "name": "client_number", "pattern": r"MDT-\d{6}", "category": "legal_data", "confidence": 0.9,
    }]))
    r = det.scan("Mandantennummer MDT-004711")
    hit = next(d for d in r.detections if d.entity_type == "client_number")
    assert hit.category == Category.LEGAL_DATA and hit.recognizer == "custom:client_number"


def test_disable_recognizer():
    r = Detector(DetectorConfig(disabled_recognizers=["email", "spacy_ner"])).scan("a@b.de")
    assert not r.detections


def test_min_confidence_moves_detections_to_suppressed():
    r = Detector(DetectorConfig(min_confidence=0.9)).scan("Termin am 03.04.2024", "de")
    assert not r.detections
    assert r.suppressed[0].reason == "below_min_confidence"


def test_ner_unavailable_degrades_with_warning():
    det = Detector(DetectorConfig(ner_models={"de": "model_that_does_not_exist"}))
    r = det.scan("Herr Max Mustermann", "de")
    assert r.warnings and "NER disabled" in r.warnings[0]
    assert r.detections


def test_language_detection():
    assert detect_language("Der Mandant ist mit dem Vergleich nicht einverstanden.") == "de"
    assert detect_language("The client is not happy with the settlement.") == "en"


# --- leak protection -----------------------------------------------------------

def test_redacted_view_contains_no_raw_values():
    text = "Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00, max@example.org"
    r = scan(text)
    dump = json.dumps([d.redacted() for d in r.detections], default=str)
    for secret in ("Mustermann", "DE89", "max@example.org"):
        assert secret not in dump


# --- mentions in other spellings ------------------------------------------------

def test_wrapped_and_upper_case_mentions_are_full_mentions():
    text = ("Unser Mandant Herr Max Mustermann wohnt hier. Später schrieb Max\nMustermann erneut.\n\n"
            "MAX MUSTERMANN\n- Kläger -\nMUSTERMANN unterschrieb.")
    persons = [d for d in RULES_ONLY.scan(text, "de").detections if d.entity_type == "person"]
    assert [d.text for d in persons] == ["Max Mustermann", "Max\nMustermann", "MAX MUSTERMANN", "MUSTERMANN"]
    assert all(text[d.start:d.end] == d.text for d in persons)
    assert {d.attributes["ref"] for d in persons} == {"person_1"}
    assert {d.attributes.get("role") for d in persons} == {"client"}


def test_surname_is_not_matched_in_arbitrary_case():
    text = "Herr Peter Weiß erschien. Er weiß davon nichts."
    persons = [d for d in RULES_ONLY.scan(text, "de").detections if d.entity_type == "person"]
    assert [d.text for d in persons] == ["Peter Weiß"]


def test_detection_id_is_independent_of_enum_or_string_type():
    a = make_detection(E.PERSON, Category.PERSONAL_DATA, 3, 9, "x", 0.5, "r")
    b = make_detection("person", Category.PERSONAL_DATA, 3, 9, "x", 0.5, "r")
    assert a.id == b.id and a.entity_type == "person"


# --- worst-case runtime -----------------------------------------------------------

@pytest.mark.parametrize("unit", ["Aa-Bb-", "1.000", "a%", "LG Aa-", "€ 1 000 ", "Mandant Aa "])
def test_scan_scales_linearly(unit):
    """Inputs that used to take quadratic time (20 s and more at this size)."""
    import time

    text = unit * (60_000 // len(unit))
    start = time.perf_counter()
    RULES_ONLY.scan(text, "de")
    assert time.perf_counter() - start < 5


def test_keep_terms_leave_own_brands_unchanged():
    from anonymizer.detect import Detector, DetectorConfig
    text = "Frau Anna Schmidt hat die ACME Mastercard bei der ACME Bank beantragt."
    kept = Detector(DetectorConfig(keep_terms=["ACME"])).scan(text, "de")
    found = [text[d.start:d.end] for d in kept.detections]
    assert not any(v.startswith("ACME") for v in found)
    assert any("Schmidt" in v for v in found)


# --- legal references (measured on German LER, see datasets/ler) ----------------------------------------
LEGAL_FOUND = [
    ("Die Befristung verstößt gegen § 14 Abs. 2 Satz 2 TzBfG.", "legal_citation", "§ 14 Abs. 2 Satz 2 TzBfG"),
    ("Zulassungsgrund nach § 160 Abs 2 Nr 3 SGG liegt nicht vor.", "legal_citation", "§ 160 Abs 2 Nr 3 SGG"),
    ("Anspruch aus § 2 Abs 1 S 3 SGB V besteht.", "legal_citation", "§ 2 Abs 1 S 3 SGB V"),
    ("vgl. BVerfGE 76, 253 < 255 >", "legal_citation", "BVerfGE 76, 253"),
    ("so Greger, in: Zöller, ZPO, 31. Auflage 2016, § 3 Rn. 4", "legal_citation", "Greger, in: Zöller, ZPO, 31. Auflage"),
    ("BVerwG, Urteil vom 18. März 2016 - 6 C 6.15 - Rn. 25", "case_number", "6 C 6.15"),
    ("BPatG, Beschluss vom 6. August 2015 - 25 W (pat) 14/14", "case_number", "25 W (pat) 14/14"),
    ("Die Entscheidung des Bundesverfassungsgerichts ist bindend.", "court", "Bundesverfassungsgerichts"),
    ("Das LSG hat die Berufung zurückgewiesen.", "court", "LSG"),
]


@pytest.mark.parametrize("text,etype,value", LEGAL_FOUND)
def test_legal_references_are_found(text, etype, value):
    found = [(d.entity_type, text[d.start:d.end]) for d in scan(text, language="de").detections]
    assert (etype, value) in found


def test_company_forms_are_not_courts_and_private_names_are_not_authors():
    types = {d.entity_type for d in
             scan("Die Siemens AG klagt. Herr Max Müller, wohnhaft in Köln, verweist auf Rn. 5.", language="de").detections}
    assert "court" not in types and "legal_citation" not in types
