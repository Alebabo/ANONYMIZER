"""Public datasets (scripts/public_pii.py): conversion to our labels, detokenizing, NER training spans."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "public_pii.py"
_spec = importlib.util.spec_from_file_location("public_pii", SCRIPT)
pp = importlib.util.module_from_spec(_spec)
sys.modules["public_pii"] = pp
_spec.loader.exec_module(pp)


@pytest.mark.parametrize("tokens, text", [
    ("Am 15 . Mai 2024 , am 25 . 05 . 2023 .", "Am 15. Mai 2024, am 25.05.2023."),
    ("Mail : hans . dieter @ gmail . com , Tel . + 49 30 123", "Mail: hans.dieter@gmail.com, Tel. +49 30 123"),
    ("SSN 123 - 45 - 1234 ( alt )", "SSN 123-45-1234 (alt)"),
    ("Er kam . Dann ging er", "Er kam. Dann ging er"),
    ("Berlin - Hamburg , E - Mail", "Berlin - Hamburg, E - Mail"),
    ("Schmidt - mueller", "Schmidt-mueller"),
])
def test_detokenize(tokens, text):
    assert pp.detokenize(tokens.split()) == text


def test_bio_spans_get_our_labels_and_lose_titles():
    tokens = "Frau Dr. Anna Müller von der Siemens AG in München ( Richter )".split()
    tags = ["B-PERSON", "I-PERSON", "I-PERSON", "I-PERSON", "O", "O", "B-ORGANIZATION_COMPANY",
            "I-ORGANIZATION_COMPANY", "O", "B-LOCATION_CITY", "O", "B-TRIGGER", "O"]
    text, spans = pp.from_bio(tokens, tags)
    assert text == "Frau Dr. Anna Müller von der Siemens AG in München (Richter)"
    assert [(text[s["start"]:s["end"]], s["label"]) for s in spans] == [
        ("Anna Müller", "person"), ("Siemens AG", "organization"), ("München", "location")]


def test_token_spans_located_in_the_original_text():
    text = "Kontakt: Max Muster, max@web.de"
    tokens = ["Kontakt", ":", "Max", "Muster", ",", "max@web.de"]
    _, spans = pp.from_token_spans(tokens, [[2, 3, "name"], [5, 5, "email"], [0, 0, "beruf"]], text)
    assert [(text[s["start"]:s["end"]], s["label"]) for s in spans] == [("Max Muster", "person"), ("max@web.de", "email")]


def test_ner_spans_skip_overlaps_and_mark_public_bodies_missing(tmp_path):
    rows = [{"id": "1", "text": "Anna Muster beim Amtsgericht Köln",
             "entities": [{"start": 0, "end": 11, "label": "person"}, {"start": 0, "end": 4, "label": "location"},
                          {"start": 17, "end": 33, "label": "public_body"}, {"start": 29, "end": 33, "label": "date"}]}]
    (tmp_path / "x").mkdir()
    with gzip.open(tmp_path / "x" / "train.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))
    assert pp.ner_spans(tmp_path, ["x", "missing-source"]) == [
        ("Anna Muster beim Amtsgericht Köln", [(0, 11, "PER")], [(17, 33)])]


def test_committed_data_loads():
    data = Path(__file__).resolve().parents[3] / "datasets" / "public"
    for source in pp.SOURCES:
        docs = pp.load(data, source)
        assert docs, source
        for _, text, gold in docs[:50]:
            assert all(0 <= s < e <= len(text) and lab in pp.TYPE_MAP | {"public_body": 0, "id_number": 0,
                                                                        "account_number": 0, "insurance_number": 0}
                       for s, e, lab in gold)


def test_join_names():
    text = "Kontakt: Birthe Schmiedt, Birthe und Max"
    spans = [{"start": 9, "end": 15, "label": "person"}, {"start": 16, "end": 24, "label": "person"},
             {"start": 26, "end": 32, "label": "person"}, {"start": 37, "end": 40, "label": "person"}]
    assert pp._join_names(text, spans) == [{"start": 9, "end": 24, "label": "person"},
                                           {"start": 26, "end": 32, "label": "person"},
                                           {"start": 37, "end": 40, "label": "person"}]


def test_source_labels():
    text = "Klinikum Kiel und Knappe Schmidt AG"
    assert pp._span(text, 0, 13, "ORGANIZATION", "medical")["label"] == "public_body"
    assert pp._span(text, 18, 35, "organization", "nobody")["label"] == "organization"
    assert pp._span(text, 18, 35, "COMPANY_NAME", "nym")["label"] == "organization"


def test_nym_unlabelled_companies_are_missing(tmp_path):
    text = "An die Buchhaltung der RideSharePlus AG, Birthe Schmiedt"
    path = tmp_path / "nym" / "train.jsonl.gz"
    path.parent.mkdir()
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "1", "text": text, "entities": [{"start": 41, "end": 56, "label": "person"}]}) + "\n")
    [(_, spans, missing)] = pp.ner_spans(tmp_path, ["nym"])
    assert spans == [(41, 56, "PER")]
    assert [text[s:e] for s, e in missing] == ["RideSharePlus AG"]
