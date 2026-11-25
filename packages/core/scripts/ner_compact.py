"""Shrink a trained spaCy pipeline for shipping, without changing its predictions.

The anonymizer only needs NER and POS tags (tok2vec, tagger, morphologizer, attribute_ruler, ner). This script
drops the other components (parser, lemmatizer, senter) and empties the string store, which holds the text of
all 500,000 vector keys (about 20 MB). Vector lookups go through the hash of the token text, so the strings are
not needed; spaCy adds the strings it meets at runtime.

The result is a standalone pipeline directory (no installed de_core_news_* package needed). Use it with
ANONYMIZER_NER_MODEL_DE=<out dir>. The script checks that entities and POS tags are identical to the source
model on a sample of texts and fails otherwise.

    python -I packages/core/scripts/ner_compact.py local/ner/models/de_unified_ner_md_e6 \
        local/ner/models/de_unified_ner_md_compact --check datasets/ler/ler_dev.jsonl.gz --limit 500
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

KEEP = ["tok2vec", "tagger", "morphologizer", "attribute_ruler", "ner"]


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def read_texts(paths: list[Path], limit: int) -> list[str]:
    texts: list[str] = []
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        count = 0
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                texts.append(json.loads(line)["text"])
                count += 1
                if limit and count >= limit:
                    break
    return texts


def compact(src: Path, out: Path, name: str = "", version: str = "") -> None:
    import spacy  # noqa: PLC0415

    nlp = spacy.load(src)
    for name in list(nlp.pipe_names):
        if name not in KEEP:
            nlp.remove_pipe(name)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "model"
        nlp.to_disk(stage)
        (stage / "vocab" / "strings.json").write_text("[]", encoding="utf-8")
        # Load once with the empty store: the components add the strings they need (labels, morph features).
        slim = spacy.load(stage)
        slim.meta["name"] = name or out.name
        if version:
            slim.meta["version"] = version
        slim.meta["description"] = (f"Compact pipeline from {src.name}: {', '.join(slim.pipe_names)}. "
                                    "Built with ner_compact.py.")
        slim.meta.setdefault("anonymizer", {})["casual"] = True
        if out.exists():
            shutil.rmtree(out)
        slim.to_disk(out)
    # spaCy rewrites the name on save; set it in meta.json directly.
    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["name"] = name or out.name
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "
", encoding="utf-8")


def check(src: Path, out: Path, texts: list[str]) -> int:
    import spacy  # noqa: PLC0415

    ref = spacy.load(src, disable=["parser", "lemmatizer", "senter"])
    new = spacy.load(out)
    diffs = 0
    for a, b in zip(ref.pipe(texts, batch_size=32), new.pipe(texts, batch_size=32), strict=True):
        ents_a = [(e.start_char, e.end_char, e.label_) for e in a.ents]
        ents_b = [(e.start_char, e.end_char, e.label_) for e in b.ents]
        if ents_a != ents_b or [t.pos_ for t in a] != [t.pos_ for t in b]:
            diffs += 1
            if diffs <= 5:
                print("DIFF:", a.text[:120].replace("\n", " "), ents_a[:5], ents_b[:5], file=sys.stderr)
    return diffs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path, help="trained pipeline directory (output of ner_train.py)")
    ap.add_argument("out", type=Path)
    ap.add_argument("--check", type=Path, nargs="*", default=[], help="JSONL(.gz) files with a 'text' field")
    ap.add_argument("--limit", type=int, default=500, help="texts per --check file (0 = all)")
    ap.add_argument("--name", default="", help="meta.json name (default: output directory name)")
    ap.add_argument("--version", default="", help="meta.json version, e.g. 1.1.0")
    args = ap.parse_args()

    compact(args.src, args.out, args.name, args.version)
    print(f"{args.src}: {dir_size(args.src) / 1e6:.1f} MB -> {args.out}: {dir_size(args.out) / 1e6:.1f} MB")
    if args.check:
        texts = read_texts(args.check, args.limit)
        diffs = check(args.src, args.out, texts)
        print(f"check: {len(texts)} texts, {diffs} with different entities or POS")
        if diffs:
            sys.exit(1)


if __name__ == "__main__":
    main()
