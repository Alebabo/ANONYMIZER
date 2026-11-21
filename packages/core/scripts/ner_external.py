"""Score the pipeline on external German PII test sets from Hugging Face (person names only).

    python packages/core/scripts/ner_external.py [--de-model MODEL] [--limit N] [-v]

Data (downloaded to local/ner/public/hf/, not part of the repository):
  syntriq      syntriq/german-pii-benchmark, test.jsonl (Apache-2.0): synthetic letters, forms and chats.
  easyoctopus  EasyOctopus/german-support-pii-data, data/test.jsonl (Apache-2.0): synthetic support messages.

Both sets label persons but not organisations or places, so only PERSON is scored: a predicted person must match
a gold person (strict: same offsets; partial: overlap). Organisation and place predictions are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
from ner_gold import predict_pipeline  # noqa: E402

from anonymizer.detect.engine import NER_STOPWORDS  # noqa: E402
from anonymizer.detect.ner import SpacyRecognizer  # noqa: E402
from anonymizer.detect.recognizers import NAME_STOPWORDS  # noqa: E402
from anonymizer.ner_dataset import DEFAULT_KEEP  # noqa: E402

SETS = {
    "syntriq": ("syntriq/test.jsonl", "entities"),
    "easyoctopus": ("easyoctopus/test.jsonl", "gold"),
}


def load(base: Path, name: str) -> list[tuple[str, str, list[tuple[int, int]]]]:
    path, field = SETS[name]
    docs = []
    for line in (base / path).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        persons = [(e["start"], e["end"]) for e in row[field] if e["label"] == "PERSON"]
        docs.append((str(row["id"]), row["text"], persons))
    return docs


def score(gold: list[tuple[int, int]], pred: list[tuple[int, int]], partial: bool) -> tuple[int, int, int]:
    def hit(a, b):
        return a == b if not partial else a[0] < b[1] and b[0] < a[1]
    tp = sum(1 for g in gold if any(hit(g, p) for p in pred))
    fp = sum(1 for p in pred if not any(hit(g, p) for g in gold))
    return tp, fp, len(gold) - tp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=Path("local/ner/public/hf"))
    ap.add_argument("--de-model", default="de_core_news_lg")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("-v", action="store_true", help="print the first 40 errors per set")
    args = ap.parse_args()
    rec = SpacyRecognizer({"de": args.de_model, "en": "en_core_web_lg"}, NAME_STOPWORDS | NER_STOPWORDS,
                          keep=list(DEFAULT_KEEP))
    for name in SETS:
        docs = load(args.dir, name)[: args.limit or None]
        totals = {False: [0, 0, 0], True: [0, 0, 0]}
        errors = []
        for key, text, gold in docs:
            pred = sorted({(s.start, s.end) for s in predict_pipeline(rec, text) if s.label == "PER"})
            for partial in (False, True):
                for i, v in enumerate(score(gold, pred, partial)):
                    totals[partial][i] += v
            for g in sorted(set(gold) - set(pred)):
                errors.append(f"{key} FN {text[g[0]:g[1]]!r}")
            for p in sorted(set(pred) - set(gold)):
                errors.append(f"{key} FP {text[p[0]:p[1]]!r}")
        for partial in (False, True):
            tp, fp, fn = totals[partial]
            p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
            f1 = 2 * p * r / max(p + r, 1e-9)
            print(f"{name:12} {'partial' if partial else 'strict ':7} PER P={p:.3f} R={r:.3f} F1={f1:.3f} "
                  f"({len(docs)} docs, {tp + fn} gold persons)")
        if args.v:
            print("\n".join(errors[:40]))


if __name__ == "__main__":
    main()
