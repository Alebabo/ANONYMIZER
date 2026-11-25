"""Stop words that are also surnames ("Richter") stay names after a first name, Herr/Frau or a party role."""

import pytest

from anonymizer.detect import Detector, DetectorConfig


def persons(text):
    return [d.text for d in Detector(DetectorConfig(enable_ner=False)).scan(text, "de").detections
            if d.entity_type == "person"]


@pytest.mark.parametrize("text, name", [
    ("Im Jahre 2000 heiratete der Angeklagte Krzysztof Richter.", "Krzysztof Richter"),
    ("Die Angeklagten Joanna Richter und Z. haben gestanden.", "Joanna Richter"),
    ("mit der Einlassung des Angeklagten Richter überein", "Richter"),
    ("Herr Richter rief an.", "Richter"),
    ("die Zeugin Richter sagte aus", "Richter"),
])
def test_richter_as_surname(text, name):
    assert name in persons(text)


def test_richter_as_title():
    assert persons("durch den Vorsitzenden Richter am Landgericht Dr. Kessler") == ["Kessler"]
    assert persons("Richterin Yilmaz und Richter Brandauer") == ["Yilmaz", "Brandauer"]
