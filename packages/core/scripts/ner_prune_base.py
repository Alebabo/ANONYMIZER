"""Base pipeline for Cato: de_core_news_lg with its vectors pruned to 20,000 rows (the size of de_core_news_md).

prune_vectors keeps the 20,000 most frequent vectors and maps every other word to its nearest kept vector, so all
500,000 keys keep a vector from the lg space. NER weights trained on de_core_news_lg (e.g. a former
models/de_legal_ner/ner) can be loaded on top and fine-tuned further.

    python -I packages/core/scripts/ner_prune_base.py local/ner/bases/lg_p20k --ner <ner weights dir>
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--ner", type=Path, help="NER weights to load (a 'ner' directory of a de_core_news_lg model)")
    args = ap.parse_args()

    import spacy  # noqa: PLC0415

    start = time.time()
    nlp = spacy.load("de_core_news_lg", exclude=["parser", "lemmatizer", "senter"])
    nlp.vocab.prune_vectors(args.rows, batch_size=4096)
    if args.ner:
        nlp.get_pipe("ner").from_disk(args.ner, exclude=["vocab"])
    nlp.to_disk(args.out)
    print(f"vectors {nlp.vocab.vectors.shape} -> {args.out} ({time.time() - start:.0f}s)")


if __name__ == "__main__":
    main()
