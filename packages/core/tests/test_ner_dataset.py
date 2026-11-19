import json

import pytest

from anonymizer.ner_dataset import (
    AnnotationError, Span, build, keep_pattern, read_gold, relevant, resolve, score_doc, summarize, write_gold,
)


def test_resolve_places_longest_first_and_skips_nested_occurrences():
    text = "Rechtsanwalt Dr. Becker, Kanzlei Becker & Partner"
    spans = resolve(text, [["PER", "Becker"], ["ORG", "Kanzlei Becker & Partner"]], required=True)
    assert [(text[s.start:s.end], s.label) for s in spans] == [("Becker", "PER"), ("Kanzlei Becker & Partner", "ORG")]


def test_resolve_matches_whole_words_only():
    assert resolve("Januar und Jan", [["PER", "Jan"]], required=True) == [Span(11, 14, "PER")]


def test_resolve_selected_occurrences():
    text = "apple.com/bill, apple kontaktiert"
    assert resolve(text, [["ORG", "apple", [1]]], required=True) == [Span(16, 21, "ORG")]
    with pytest.raises(AnnotationError):
        resolve(text, [["ORG", "apple", [2]]], required=True)


def test_resolve_rejects_missing_or_bad_entries():
    with pytest.raises(AnnotationError):
        resolve("kein Name", [["PER", "Müller"]], required=True)
    assert resolve("kein Name", [["PER", "Müller"]], required=False) == []
    with pytest.raises(AnnotationError):
        resolve("Müller", [["NAME", "Müller"]], required=True)
    with pytest.raises(AnnotationError):
        resolve("Müller", [["PER", " Müller"]], required=True)


def test_build_roundtrip(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = [{"source": "chat_cand", "db_id": 1, "md5": "", "text": "Ich bin Tuca"},
            {"source": "chat_random", "db_id": 1, "md5": "", "text": "Ich bin Tuca"},
            {"source": "mail", "db_id": 2, "md5": "", "text": "Gruß\nNina Falk"}]
    (raw / "chat_cand.jsonl").write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    (raw / "chat_random.jsonl").write_text(json.dumps(rows[1]) + "\n", encoding="utf-8")
    (raw / "mail.jsonl").write_text(json.dumps(rows[2]) + "\n", encoding="utf-8")
    ann = tmp_path / "a.json"
    ann.write_text(json.dumps({"global": [["PER", "Nina Falk"]], "docs": {"chat:1": [["PER", "Tuca"]]}}),
                   encoding="utf-8")
    docs = build(raw, ann)
    assert [(d.key, d.subsets) for d in docs] == [("chat:1", ["chat_cand", "chat_random"]), ("mail:2", ["mail"])]
    write_gold(docs, tmp_path / "gold.jsonl")
    back = read_gold(tmp_path / "gold.jsonl")
    assert [(d.text[s.start:s.end], s.label) for d in back for s in d.spans] == [("Tuca", "PER"), ("Nina Falk", "PER")]

    ann.write_text(json.dumps({"docs": {"chat:99": []}}), encoding="utf-8")
    with pytest.raises(AnnotationError):
        build(raw, ann)


def test_score_strict_and_partial():
    gold = [Span(0, 12, "PER"), Span(20, 26, "LOC"), Span(30, 60, "ADDR")]
    pred = [Span(0, 12, "PER"), Span(20, 24, "LOC"), Span(40, 45, "ORG")]
    text = "x" * 60
    pred = [p for p in pred if relevant(p, text, gold, None)]  # the ORG inside the address is not scored
    strict, fps, fns = score_doc(gold, pred, partial=False)
    assert (strict["PER"].tp, strict["LOC"].fp, strict["LOC"].fn) == (1, 1, 1)
    assert fps == [Span(20, 24, "LOC")] and fns == [Span(20, 26, "LOC")]
    partial, fps, fns = score_doc(gold, pred, partial=True)
    assert (partial["LOC"].tp, fps, fns) == (1, [], [])
    s = summarize([("mail:1", strict)])
    assert s["micro"] == {"tp": 1, "fp": 1, "fn": 1, "precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_keep_terms_are_ignored_like_the_pipeline():
    keep = keep_pattern(["ACME", "ACMECOMPARE"])
    text = "ACME Bank und ACMECOMPARE und ACME5"
    assert not relevant(Span(0, 9, "ORG"), text, [], keep)
    assert not relevant(Span(14, 25, "ORG"), text, [], keep)
    assert relevant(Span(30, 35, "ORG"), text, [], keep)
