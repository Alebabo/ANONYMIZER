"""VAT IDs are found with and without the usual spaces, but never across a line break."""

import pytest

from anonymizer.detect.recognizers import IBAN, VAT_ID


@pytest.mark.parametrize("text, value", [
    ("USt-IdNr.: DE298765432", "DE298765432"),
    ("USt-IdNr.: DE 298765432", "DE 298765432"),
    ("USt-IdNr.: DE 298 765 432.", "DE 298 765 432"),
    ("USt-IdNr. DE298 765 432", "DE298 765 432"),
    ("UID: ATU12345678", "ATU12345678"),
    ("UID: ATU 12345678", "ATU 12345678"),
])
def test_vat_id_with_spaces(text, value):
    assert [d.text for d in VAT_ID.analyze(text, "de")] == [value]


@pytest.mark.parametrize("text", [
    "IBAN DE89 3704 0044 0532 0130 00",
    "DE\n298 765 432",
    "DE 298 765 4321",
])
def test_vat_id_not_matched(text):
    assert list(VAT_ID.analyze(text, "de")) == []


def test_iban_unchanged():
    assert [d.text for d in IBAN.analyze("IBAN DE89 3704 0044 0532 0130 00", "de")] == ["DE89 3704 0044 0532 0130 00"]
