"""Streets named with a preposition ("Am Wall 112") count as addresses only with postcode and city."""

import pytest

from anonymizer.detect import Detector

detector = Detector()


def addresses(text: str) -> list[str]:
    return [d.text for d in detector.scan(text, "de").detections if d.entity_type == "address"]


@pytest.mark.parametrize("text, expected", [
    ("Am Wall 112 · 28195 Bremen", "Am Wall 112 · 28195 Bremen"),
    ("Am Wall 112 - 28195 Bremen - Tel. 0421 5566778", "Am Wall 112 - 28195 Bremen"),
    ("An der Alster 5, 20099 Hamburg", "An der Alster 5, 20099 Hamburg"),
    ("Im Tal 3\n80331 München", "Im Tal 3\n80331 München"),
])
def test_found(text, expected):
    assert expected in addresses(text)


@pytest.mark.parametrize("text", [
    "Im Jahr 2025 stieg der Umsatz.", "Am Ende 3 Wochen später", "Zum Termin 14 Uhr erschien niemand.",
    "Auf der Sitzung 12 Teilnehmer", "Am 12.03.2024 in Bremen",
])
def test_not_found(text):
    assert addresses(text) == []
