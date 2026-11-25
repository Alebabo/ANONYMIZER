"""Experimental transformer NER (detect/hf_ner.py): window merging and BIO decoding with a fake model,
so neither weights nor a download are needed (torch is required)."""

from __future__ import annotations

import pytest

from anonymizer.detect import hf_ner

torch = pytest.importorskip("torch")


def test_bio_spans():
    labels = ["O", "B-PER", "I-PER", "I-ORG", "O", "I-LOC", "B-LOC", "B-LOC"]
    assert hf_ner.bio_spans(labels) == [(1, 3, "PER"), (3, 4, "ORG"), (5, 6, "LOC"), (6, 7, "LOC"), (7, 8, "LOC")]


class _Enc(dict):
    def __init__(self, ids, word_ids):
        super().__init__(input_ids=torch.tensor(ids), attention_mask=torch.ones(len(ids), len(ids[0]), dtype=torch.long))
        self._w = word_ids

    def word_ids(self, i):
        return self._w[i]


class FakeTokenizer:
    """Two overlapping windows over five words: [CLS] w0 w1 w2 [SEP] [PAD] and [CLS] w1 w2 w3 w4 [SEP]."""

    def __call__(self, words, **kw):
        return _Enc([[0, 1, 2, 3, 0, 0], [0, 2, 3, 4, 5, 0]],
                    [[None, 0, 1, 2, None, None], [None, 1, 2, 3, 4, None]])


class FakeModel:
    """Labels a subword by its id; word 2 is B-PER in window 1 (at its edge) and O in window 2 (one token in)."""

    class config:
        id2label = {0: "O", 1: "B-PER", 2: "I-PER"}

    def __call__(self, input_ids, attention_mask):
        table = {0: 0, 1: 1, 2: 2, 3: 1, 4: 0, 5: 0}
        logits = torch.zeros(*input_ids.shape, 3)
        for r, row in enumerate(input_ids.tolist()):
            for c, tok in enumerate(row):
                lab = table[tok] if not (r == 1 and tok == 3) else 0
                logits[r, c, lab] = 1.0
        return type("Out", (), {"logits": logits})()


def test_word_labels_take_the_window_where_the_word_is_central():
    labels = hf_ner.word_labels(FakeModel(), FakeTokenizer(), ["a", "b", "c", "d", "e"])
    assert labels == ["B-PER", "I-PER", "O", "O", "O"]


def test_is_hf_model(tmp_path):
    assert not hf_ner.is_hf_model(tmp_path)
    (tmp_path / "config.json").write_text("{}")
    assert hf_ner.is_hf_model(tmp_path)
