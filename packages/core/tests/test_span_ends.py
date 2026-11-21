"""Rule detections end at the line or sentence: a case number or address never takes the next sentence."""

import pytest

from anonymizer.detect.recognizers import ADDRESS, CASE_NUMBER


@pytest.mark.parametrize("text, value", [
    ("Az.: 12 C 345/24\nDer Kläger", "12 C 345/24"),
    ("Az.: 12 C 345/24. Der Kläger", "12 C 345/24"),
    ("Aktenzeichen 2 O 123/24 Die Beklagte", "2 O 123/24"),
    ("Case No. 1:23-cv-01234 The court", "1:23-cv-01234"),
    ("Az.: 123 Js 4567/24 X", "123 Js 4567/24 X"),
    ("Unser Zeichen: MDT-2024/0815 KS", "MDT-2024/0815 KS"),
])
def test_case_number_does_not_swallow_the_next_sentence(text, value):
    assert max((d.text for d in CASE_NUMBER.analyze(text, "de")), key=len) == value


@pytest.mark.parametrize("text, value", [
    ("Hauptstraße 12, 10115 Berlin\n\nIn der Sache", "Hauptstraße 12, 10115 Berlin"),
    ("Hauptstraße 12, 10115 Berlin\nDer Kläger", "Hauptstraße 12, 10115 Berlin"),
    ("Hauptstraße 12, 10115 Berlin In der Sache", "Hauptstraße 12, 10115 Berlin"),
    ("Hauptstraße 12, 60311 Frankfurt am Main. Der", "Hauptstraße 12, 60311 Frankfurt am Main"),
    ("Hauptstraße 12\n10115 Frankfurt am Main", "Hauptstraße 12\n10115 Frankfurt am Main"),
    ("Lindenweg 3, 12345 Berlin-Mitte", "Lindenweg 3, 12345 Berlin-Mitte"),
])
def test_address_ends_at_the_line(text, value):
    assert [d.text for d in ADDRESS.analyze(text, "de")] == [value]
