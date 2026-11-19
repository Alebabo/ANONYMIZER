"""Build the NER gold set and measure the spaCy NER against it.

    python packages/core/scripts/ner_gold.py build  [--dir local/ner]
    python packages/core/scripts/ner_gold.py eval   [--dir local/ner] [--de-model de_core_news_lg]
    python packages/core/scripts/ner_gold.py review [--dir local/ner]

build:  raw/*.jsonl + annotations.json -> gold.jsonl (fails on any annotation that does not fit the text)
        and reports spans that do not line up with spaCy tokens (those cannot be used for training as is).
eval:   precision/recall/F1 for the raw model output and for the pipeline recognizer (clean-up filters,
        keep terms), strict and partial; writes eval_<model>.json and errors_<model>.md.
review: writes review.md, every document with its gold spans and the model's disagreements, for checking
        the annotations by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from anonymizer.detect.engine import NER_STOPWORDS, detect_language
from anonymizer.detect.ner import _LABELS, DEFAULT_MODELS, SpacyRecognizer
from anonymizer.detect.recognizers import NAME_STOPWORDS
from anonymizer.models import EntityType as E
from anonymizer.ner_dataset import (
    DEFAULT_KEEP, GoldDoc, Span, build, keep_pattern, label_counts, read_gold, relevant, score_doc, summarize,
    write_gold,
)

TYPE_TO_LABEL = {E.PERSON: "PER", E.ORGANIZATION: "ORG", E.LOCATION: "LOC"}


def languages(text: str, models: dict[str, str]) -> list[str]:
    lang = detect_language(text)
    return [lang] if lang in models else list(models)


def predict_raw(rec: SpacyRecognizer, text: str) -> list[Span]:
    out: set[tuple[int, int, str]] = set()
    for lang in languages(text, rec.models):
        for ent in rec._nlp(lang)(text).ents:
            mapped = _LABELS.get(ent.label_)
            if mapped:
                out.add((ent.start_char, ent.end_char, TYPE_TO_LABEL[mapped[0]]))
    return [Span(*s) for s in sorted(out)]


def predict_pipeline(rec: SpacyRecognizer, text: str) -> list[Span]:
    out: set[tuple[int, int, str]] = set()
    for lang in languages(text, rec.models):
        for d in rec.analyze(text, lang):
            if d.entity_type in TYPE_TO_LABEL:
                out.add((d.start, d.end, TYPE_TO_LABEL[d.entity_type]))
    return [Span(*s) for s in sorted(out)]


def cmd_build(base: Path) -> None:
    docs = build(base / "raw", base / "annotations.json")
    write_gold(docs, base / "gold.jsonl")
    counts = label_counts(docs)
    by_source: dict[str, int] = {}
    for d in docs:
        by_source[d.source] = by_source.get(d.source, 0) + 1
    print(f"gold.jsonl: {len(docs)} docs {by_source}, spans {dict(counts)}, "
          f"docs with entities {sum(1 for d in docs if any(s.label != 'ADDR' for s in d.spans))}")
    import spacy  # noqa: PLC0415

    tok = spacy.blank("de")
    misaligned = []
    for d in docs:
        doc = tok(d.text)
        for s in d.spans:
            if doc.char_span(s.start, s.end) is None:
                misaligned.append(f"{d.key} {s.label} {d.text[s.start:s.end]!r}")
    print(f"spans not on token boundaries (blank 'de' tokenizer): {len(misaligned)}")
    for m in misaligned:
        print("  " + m)


def _score(docs: list[GoldDoc], predict, rec: SpacyRecognizer, keep) -> tuple[dict, dict, list]:
    strict, partial, errors = [], [], []
    for d in docs:
        pred = [p for p in predict(rec, d.text) if relevant(p, d.text, d.spans, keep)]
        s, fps, fns = score_doc(d.spans, pred, partial=False)
        strict.append((d.key, s))
        partial.append((d.key, score_doc(d.spans, pred, partial=True)[0]))
        if fps or fns:
            errors.append((d, fps, fns))
    return summarize(strict), summarize(partial), errors


def _unseen_recall(docs: list[GoldDoc], train_strings: set[str], errors: list) -> dict:
    """Recall on test spans whose text never occurs as an entity in the train split: memory does not help."""
    missed = {(d.key, g.start, g.end) for d, _, fns in errors for g in fns}
    total = found = 0
    for d in docs:
        for s in d.spans:
            if s.label == "ADDR" or d.text[s.start:s.end].lower() in train_strings:
                continue
            total += 1
            found += (d.key, s.start, s.end) not in missed
    return {"spans": total, "recall": round(found / total, 3) if total else None}


def cmd_eval(base: Path, de_model: str, split: str) -> None:
    gold = read_gold(base / "gold.jsonl")
    docs = [d for d in gold if split == "all" or d.split == split]
    train_strings = {d.text[s.start:s.end].lower() for d in gold if d.split == "train" for s in d.spans}
    models = {**DEFAULT_MODELS, "de": de_model}
    rec = SpacyRecognizer(models, NAME_STOPWORDS | NER_STOPWORDS, keep=list(DEFAULT_KEEP))
    keep = keep_pattern(DEFAULT_KEEP)
    result, md = {"model": models, "split": split, "documents": len(docs)}, []
    for mode, fn in (("raw", predict_raw), ("pipeline", predict_pipeline)):
        strict, partial, errors = _score(docs, fn, rec, keep)
        result[mode] = {"strict": strict, "partial": partial,
                        "unseen_recall_strict": _unseen_recall(docs, train_strings, errors)}
        md.append(f"## {mode}: {len(errors)} documents with errors\n")
        for d, fps, fns in errors:
            md.append(f"### {d.key}\n")
            md += [f"- FP {p.label} `{d.text[p.start:p.end]}`" for p in fps]
            md += [f"- FN {g.label} `{d.text[g.start:g.end]}`" for g in fns]
            md.append("")
    name = f"{Path(de_model).name}_{split}"
    (base / f"eval_{name}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (base / f"errors_{name}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"{split}: {len(docs)} docs")
    for mode in ("raw", "pipeline"):
        for kind in ("strict", "partial"):
            r = result[mode][kind]
            labels = "  ".join(f"{k} P={v['precision']} R={v['recall']} F1={v['f1']}" for k, v in r["labels"].items())
            print(f"{mode:8} {kind:7} micro P={r['micro']['precision']} R={r['micro']['recall']} "
                  f"F1={r['micro']['f1']} | {labels}")
        u = result[mode]["unseen_recall_strict"]
        print(f"{mode:8} unseen  recall={u['recall']} on {u['spans']} spans not in the train split")
    print(f"written: eval_{name}.json, errors_{name}.md")


def cmd_review(base: Path) -> None:
    docs = read_gold(base / "gold.jsonl")
    rec = SpacyRecognizer(None, NAME_STOPWORDS | NER_STOPWORDS, keep=list(DEFAULT_KEEP))
    keep = keep_pattern(DEFAULT_KEEP)
    out = ["# NER gold review", "", "Gold spans per document; `model+` = raw model prediction not in gold, "
           "`model-` = gold span the raw model misses (strict).", ""]
    for d in docs:
        pred = [p for p in predict_raw(rec, d.text) if relevant(p, d.text, d.spans, keep)]
        _, fps, fns = score_doc(d.spans, pred, partial=False)
        out.append(f"## {d.key} ({', '.join(d.subsets)})" + (f" — REVIEW: {d.review}" if d.review else ""))
        out.append("```text\n" + d.text.replace("```", "'''") + "\n```")
        out += [f"- gold {s.label} `{d.text[s.start:s.end]}`" for s in d.spans] or ["- gold: none"]
        out += [f"- model+ {p.label} `{d.text[p.start:p.end]}`" for p in fps]
        out += [f"- model- {g.label} `{d.text[g.start:g.end]}`" for g in fns]
        out.append("")
    (base / "review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"written: review.md ({len(docs)} docs)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["build", "eval", "review"])
    ap.add_argument("--dir", default="local/ner", type=Path)
    ap.add_argument("--de-model", default=DEFAULT_MODELS["de"], help="spaCy model name or path for German")
    ap.add_argument("--split", default="test", choices=["test", "dev", "train", "all"])
    args = ap.parse_args()
    if args.command == "build":
        cmd_build(args.dir)
    elif args.command == "eval":
        cmd_eval(args.dir, args.de_model, args.split)
    else:
        cmd_review(args.dir)


if __name__ == "__main__":
    sys.exit(main())
