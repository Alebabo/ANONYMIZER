"""Transformer token classifier (Hugging Face) as the NER component of a spaCy pipeline.

Experimental, off by default. ``ANONYMIZER_NER_MODEL_DE="<cato dir>+<hf dir>"`` replaces Cato's NER with a
fine-tuned token classifier from ``scripts/tf_train.py``; tagger, morphologizer and every rule after NER in
``detect/ner.py`` (authority check, cleaning, signature lines, lower-case chat) stay exactly as with Cato, so a
measurement compares only the NER. A directory counts as a Hugging Face model when it holds ``config.json``.

Needs ``torch`` and ``transformers`` (not part of the default install). Long texts are cut into windows of
``max_length`` subword tokens with ``stride`` tokens of overlap; a word's label comes from its first subword,
taken from the window where the word sits furthest from an edge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_LENGTH = 512
STRIDE = 128
FACTORY = "hf_token_ner"


def is_hf_model(path: str | Path) -> bool:
    return (Path(path) / "config.json").is_file()


def word_labels(model: Any, tokenizer: Any, words: list[str], max_length: int = MAX_LENGTH,
                stride: int = STRIDE, batch_size: int = 8) -> list[str]:
    """One BIO label per word (pre-split words, as spaCy tokens)."""
    import torch  # noqa: PLC0415

    if not words:
        return []
    enc = tokenizer(words, is_split_into_words=True, truncation=True, max_length=max_length, stride=stride,
                    return_overflowing_tokens=True, padding=True, return_tensors="pt")
    id2label = model.config.id2label
    device = getattr(model, "device", "cpu")
    best: dict[int, tuple[int, str]] = {}  # word -> (distance to the window edge, label)
    n = enc["input_ids"].shape[0]
    with torch.inference_mode():
        for lo in range(0, n, batch_size):
            batch = {k: enc[k][lo:lo + batch_size].to(device) for k in ("input_ids", "attention_mask")}
            logits = model(**batch).logits
            for row, pred in enumerate(logits.argmax(-1).tolist()):
                ids = enc.word_ids(lo + row)
                positions = [i for i, w in enumerate(ids) if w is not None]
                first, last = positions[0], positions[-1]
                prev = None
                for i, w in enumerate(ids):
                    if w is None or w == prev:
                        prev = w
                        continue
                    prev = w
                    margin = min(i - first, last - i)
                    if w not in best or margin > best[w][0]:
                        best[w] = (margin, id2label[pred[i]])
    return [best.get(i, (0, "O"))[1] for i in range(len(words))]


def bio_spans(labels: list[str]) -> list[tuple[int, int, str]]:
    """BIO labels -> (first word, end word exclusive, label); a stray I- starts a new entity."""
    out: list[tuple[int, int, str]] = []
    cur: list | None = None
    for i, lab in enumerate(labels):
        kind, _, name = lab.partition("-")
        if kind == "B" or (kind == "I" and (cur is None or cur[2] != name)):
            cur = [i, i + 1, name]
            out.append(cur)
        elif kind == "I":
            cur[1] = i + 1
        else:
            cur = None
    return [tuple(c) for c in out]


class HFTokenNER:
    """spaCy component: sets ``doc.ents`` from the token classifier (PER, ORG, LOC, ...)."""

    def __init__(self, path: str, batch_size: int = 8) -> None:
        from transformers import AutoModelForTokenClassification, AutoTokenizer  # noqa: PLC0415

        self.path = path
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        import torch  # noqa: PLC0415

        self.model = AutoModelForTokenClassification.from_pretrained(path).eval()
        if torch.cuda.is_available():
            self.model.to("cuda")
        self.batch_size = batch_size

    def __call__(self, doc: Any) -> Any:
        from spacy.tokens import Span  # noqa: PLC0415
        from spacy.util import filter_spans  # noqa: PLC0415

        # Whitespace tokens ("\n\n") are not words for the tokenizer; they stay O.
        idx = [t.i for t in doc if not t.is_space]
        labels = word_labels(self.model, self.tokenizer, [doc[i].text for i in idx], batch_size=self.batch_size)
        spans = [Span(doc, idx[a], idx[b - 1] + 1, label=lab) for a, b, lab in bio_spans(labels)]
        doc.ents = filter_spans(spans)
        return doc

    def pipe(self, docs, batch_size: int = 8):
        for doc in docs:
            yield self(doc)


def replace_ner(nlp: Any, path: str) -> Any:
    """Swap the pipeline's "ner" for the token classifier at ``path`` (same name, so callers are unchanged)."""
    from spacy.language import Language  # noqa: PLC0415

    if not Language.has_factory(FACTORY):
        Language.factory(FACTORY, default_config={"path": ""})(lambda nlp, name, path: HFTokenNER(path))
    if "ner" in nlp.pipe_names:
        nlp.replace_pipe("ner", FACTORY, config={"path": str(path)})
    else:
        nlp.add_pipe(FACTORY, name="ner", config={"path": str(path)})
    return nlp
