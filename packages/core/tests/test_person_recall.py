"""Person recall in legal text: judges' benches and signature lines."""

from pathlib import Path

import pytest

from anonymizer.detect import Detector, DetectorConfig
from anonymizer.detect.ner import _ISOLATED, _ADJECTIVE_END
from anonymizer.detect.recognizers import PERSON

LEGAL_NER = Path(__file__).resolve().parents[3] / "models" / "de_legal_ner" / "ner"


def persons(text: str) -> list[str]:
    return [d.text for d in PERSON.analyze(text, "de")]


# --- bench of judges ---------------------------------------------------------

def test_all_judges_of_a_bench_are_found():
    text = "unter Mitwirkung der Vorsitzenden Richterin Kortge sowie der Richter Jacobi und Schödel beschlossen:"
    assert set(persons(text)) == {"Kortge", "Jacobi", "Schödel"}
    assert set(persons("durch die Richter Merzbach, Dr. Meiser und Schödel")) == {"Merzbach", "Meiser", "Schödel"}
    assert set(persons("die Richterinnen Baer und Britz")) == {"Baer", "Britz"}


def test_bench_rule_needs_an_article_and_stops_at_non_names():
    # An enumeration of professions is no bench.
    assert "Rechtspfleger" not in persons("Anordnungen für Richter, Staatsanwälte und Rechtspfleger, die")
    assert persons("der Richter Müller, Die Kammer hat") == ["Müller"]
    assert persons("der Richter Dipl.-Ing. Matter und Dipl. - Phys. Dr. Wahl") == ["Matter", "Wahl"]
    assert persons("die Richter Bauer und Proberichter Kunz")[:1] == ["Bauer"]
    assert "Proberichter" not in persons("die Richter Bauer und Proberichter")


def test_judge_abbreviation_is_a_role():
    assert persons("RiBGH Gericke befindet sich im Urlaub") == ["Gericke"]


# --- isolated names (signature lines) ----------------------------------------

def isolated(text: str) -> list[str]:
    return [m.group("name") for m in _ISOLATED.finditer(text)]


def test_isolated_word_candidates():
    assert isolated("Hierüber hat der Senat entschieden. Fieback bb) Aus den Gründen") == ["Fieback"]
    assert isolated("Insoweit ist sie zulässig. Raum Nicht anders als") == ["Raum"]
    assert isolated("Hayen") == ["Hayen"]
    assert isolated("Ausgefertigt\nRaum\nFieback\n") == ["Ausgefertigt", "Raum", "Fieback"]
    # Running text, abbreviations and enumerations are no candidates.
    assert "Müller" not in isolated("Der Kläger Müller hat geklagt.")
    assert isolated("vgl. D1 u. a. Schutzansprüche 1 und 2") == []
    assert isolated("2. Gleichheitsrechtliche Anforderungen") == []
    assert isolated('die Bezeichnung " Compositions Comprising') == []
    assert isolated("(Gruppe 1: Sanitätsstabsoffizier Zahnarzt)") == []


def test_adjectives_are_no_isolated_names():
    assert _ADJECTIVE_END.search("Statthafte")
    assert _ADJECTIVE_END.search("Gleichheitsrechtliche")
    assert not _ADJECTIVE_END.search("Fieback")
    assert not _ADJECTIVE_END.search("Schmidt")


@pytest.fixture(scope="module")
def legal_detector() -> Detector:
    if not (LEGAL_NER / "model").exists() or (LEGAL_NER / "model").stat().st_size < 10_000:
        pytest.skip("de_legal_ner weights not available (git lfs pull)")
    det = Detector(DetectorConfig(ner_models={"de": f"de_core_news_lg+{LEGAL_NER}"}))
    if det.scan("Herr Max Mustermann", "de").warnings:
        pytest.skip("spaCy model de_core_news_lg not installed")
    return det


def test_signature_names_are_persons_and_headings_are_not(legal_detector):
    text = ("Die Beschwerde wird zurückgewiesen. Fieback bb) Aus den vorstehenden Ausführungen folgt das. "
            "Raum Nicht anders als bei der Sozietät.\n\nTatbestand\nGeltungsbereich\nBeglaubigt\nHayen\n")
    found = {d.text for d in legal_detector.scan(text, "de").detections if d.entity_type == "person"}
    assert {"Fieback", "Raum", "Hayen"} <= found
    assert not found & {"Tatbestand", "Geltungsbereich", "Beglaubigt"}


def test_isolated_check_only_with_the_legal_model():
    from anonymizer.detect.ner import SpacyRecognizer

    assert SpacyRecognizer({"de": "de_core_news_lg"})._isolated == set()
    assert SpacyRecognizer({"de": "de_core_news_lg+models/de_c24_ner/ner"})._isolated == set()
    assert SpacyRecognizer({"de": "de_core_news_lg+models/de_legal_ner/ner"})._isolated == {"de"}
