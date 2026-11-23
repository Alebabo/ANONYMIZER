"""Playground with NER on: column hints win, no over-redaction of common nouns and IDs.

Skipped when spaCy or the German model is missing.
"""

import pytest

from anonymizer.accounts import LOCAL_PRINCIPAL
from anonymizer.detect import Detector, DetectorConfig
from anonymizer.pipeline import Pipeline
from anonymizer.playground import PlaygroundService, PlaygroundStore
from anonymizer.policy import builtin_policy

CSV = (
    "kunden_id;vorname;nachname;email;telefon;iban;anliegen\n"
    "K-1001;Max;Mustermann;max.mustermann@example.org;0151 23456789;DE89370400440532013000;"
    "Herr Mustermann möchte sein Dispolimit erhöhen, bitte Rückruf.\n"
    "K-1002;Erika;Musterfrau;erika@example.org;030 1234567;DE02120300000000202051;"
    "Karte gesperrt nach Urlaub in Spanien, Frau Musterfrau ist verärgert.\n"
    "K-1003;Jan;Beispiel;jan.b@example.org;;DE02500105170137075030;"
    "Frage zur Überweisung vom 12.11. an Peter Schmidt.\n"
)


def _ner_available() -> bool:
    return not Detector().scan("Herr Max Mustermann", "de").warnings


pytestmark = pytest.mark.skipif(not _ner_available(), reason="spaCy models not installed")


@pytest.fixture(scope="module")
def rows():
    det = Detector(DetectorConfig(enable_ner=True))
    svc = PlaygroundService(PlaygroundStore(),
                            lambda v: Pipeline(builtin_policy("support-default"), detector=det, vault=v),
                            "support-default")
    ds = svc.upload(LOCAL_PRINCIPAL, "kunden.csv", CSV)
    return svc.query(LOCAL_PRINCIPAL, ds["id"])["rows"]


def test_hinted_column_type_wins(rows):
    for row in rows:
        assert row["vorname"].startswith("PERSON_"), row
        assert row["nachname"].startswith("PERSON_"), row
        assert row["email"].startswith("EMAIL_")
    assert rows[0]["telefon"].startswith("PHONE_") and rows[1]["telefon"].startswith("PHONE_")
    assert all("DE" not in r["iban"] for r in rows)


def test_same_value_same_placeholder_in_column_and_free_text(rows):
    assert rows[0]["anliegen"].startswith(f"Herr {rows[0]['nachname']} ")
    assert f"Frau {rows[1]['nachname']} " in rows[1]["anliegen"]


def test_common_nouns_are_not_redacted_and_ids_get_number_placeholders(rows):
    assert rows[0]["anliegen"].endswith("möchte sein Dispolimit erhöhen, bitte Rückruf.")
    assert rows[1]["anliegen"].startswith("Karte gesperrt nach Urlaub in ")
    # numbers of 4+ digits are placeholders (support-default "numbers"); the id prefix stays readable
    ids = [r["kunden_id"] for r in rows]
    assert all(i.startswith("K-NUMBER_") for i in ids) and len(set(ids)) == 3


def test_real_names_still_detected(rows):
    text = str(rows)
    for name in ("Max", "Mustermann", "Erika", "Musterfrau", "Peter", "Schmidt", "Jan", "Beispiel"):
        assert name not in text, name
    assert "an PERSON_" in rows[2]["anliegen"]


def test_short_german_rows_are_detected_as_german():
    from anonymizer.detect import detect_language

    assert detect_language("Karte gesperrt nach Urlaub in Spanien, Frage zur Überweisung an Peter.") == "de"
    assert detect_language("Please call me back, the card is blocked.") == "en"


def test_ner_span_with_plain_lower_case_word_is_not_a_person():
    r = Detector().scan("Herr Mustermann möchte sein Dispolimit erhöhen.", "en")
    assert not [d for d in r.detections if d.entity_type in ("person", "organization") and " " in d.text
                and any(t.islower() for t in d.text.split())]
