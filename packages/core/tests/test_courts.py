"""Court decisions: the court's "…" placeholders become synthetic values with exact spans."""

import re

from anonymizer import scan
from anonymizer.courts import PH, Filler, build_doc, clean_html, fill, split_of
from anonymizer.ler import Names

TEXT = ("Der Zeuge Herr … sagte aus. Die Klägerin wohnt in der …straße 12 in 12345 …. "
        "Sie unterhält ein Konto bei der … Bank, IBAN …. Die M... H... GmbH & Co. KG ist beteiligt. "
        "Der am … verstorbene Erblasser; Aktenzeichen … beim Amtsgericht. Flug von … nach … gebucht. "
        "Wie bereits ausgeführt … bleibt es dabei.")


def doc():
    return fill(TEXT, Filler(Names(3, held_out=False)))


def test_placeholders_get_values_and_exact_spans():
    new, spans = doc()
    got = {s.label: new[s.start:s.end] for s in spans}
    assert set(got) >= {"PER", "ADDR", "LOC", "ORG", "IBAN", "DATE", "AZ"}
    assert re.fullmatch(r"\S+straße 12", got["ADDR"])
    orgs = [new[s.start:s.end] for s in spans if s.label == "ORG"]
    assert any(o.endswith(" Bank") for o in orgs) and any(o.endswith("GmbH & Co. KG") for o in orgs)
    assert "M..." not in new and "H..." not in new          # a run of initials became one name
    assert "ausgeführt … bleibt" in new                       # a bare ellipsis without context stays
    assert re.search(r"12345 \w+\. Sie", new)                # the full stop after "…." is kept
    for s in spans:                                           # every span sits on word boundaries
        assert not (s.start and new[s.start - 1].isalnum())
        assert not (s.end < len(new) and new[s.end].isalnum() and s.label != "ADDR")


def test_placeholder_pattern_is_one_group():
    # Regression: an ungrouped alternative in PH once broke every rule that embedded it.
    assert re.fullmatch(rf"von\s{PH}\snach", "von … nach") and not re.search(rf"x{PH}y", "xy")


def test_synthetic_iban_passes_the_checksum():
    new, spans = doc()
    iban = next(new[s.start:s.end] for s in spans if s.label == "IBAN")
    assert [d.entity_type for d in scan(f"IBAN {iban}", language="de").detections] == ["iban"]


def test_html_cleanup_and_split():
    assert clean_html("<p>Herr&nbsp;…</p><p>sagte</p>") == "Herr …\n\nsagte"
    assert {split_of(i) for i in range(200)} == {"train", "dev", "test"}
    case = {"id": 7, "court": {"name": "Amtsgericht Köln"}}
    d = build_doc(case, "Es erschien Frau … mit ihrem Anwalt.", "train")
    assert d is not None and d.spans[0].label == "PER" and d.key == "courts:7"
    assert build_doc(case, "Nichts zu ersetzen.", "train") is None
