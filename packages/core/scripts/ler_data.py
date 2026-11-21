"""German LER (court decisions) as gold data: download, convert, measure the whole detection pipeline.

    python packages/core/scripts/ler_data.py download [--dir local/ler]
    python packages/core/scripts/ler_data.py build    [--dir local/ler] [--out datasets/ler]
    python packages/core/scripts/ler_data.py eval     [--data datasets/ler] [--split dev] [--limit 400] [--no-ner]

download: the CoNLL files of https://github.com/elenanereiss/Legal-Entity-Recognition (CC BY 4.0).
build:    ler_{train,dev,test}.jsonl.gz in the gold format of anonymizer.ner_dataset, with synthetic names in
          place of the anonymized ones (see anonymizer.ler). These files are committed; training reads them.
eval:     runs the detector (rules + spaCy NER, exactly as the API) and reports
          * persons / organisations / locations: precision, recall, F1 (partial overlap and strict)
          * public references: share of courts, laws and case law found by the rule recognizers
          * false positives: person/organisation/location detections on courts, laws, case law (these would be
            pseudonymized and make a legal text unreadable)
          Writes eval_<split>.json and errors_<split>.md next to the data.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

from anonymizer.detect import Detector, DetectorConfig
from anonymizer.ler import PUBLIC_LABELS, build_docs, read_conll
from anonymizer.ner_dataset import GoldDoc, Span, read_gold, score_doc, summarize, write_gold

BASE = "https://raw.githubusercontent.com/elenanereiss/Legal-Entity-Recognition/master/data"
FILES = ("ler_train.conll", "ler_dev.conll", "ler_test.conll")
TYPE_TO_LABEL = {"person": "PER", "organization": "ORG", "location": "LOC"}
# Which rule types count as "found" for a public reference label.
RULE_TYPES = {"GRT": {"court"}, "GS": {"legal_citation"}, "RS": {"case_number", "legal_citation", "court"}}
# A case number inside a case-law reference ("VI ZR 12/20", "7 B 261.97", "1 BvR 2075/17").
AZ = re.compile(r"(?<![\w/.])(?:\d{1,3}|[IVX]{1,5})\s?[A-Z][A-Za-z]{0,4}(?:\s\([a-z]+\))?\s\d{1,5}[/.]\d{2}(?![\w/])")


def cmd_download(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        target = base / f
        if target.exists():
            print(f"{f}: present")
            continue
        with urllib.request.urlopen(f"{BASE}/{f}", timeout=120) as r:  # noqa: S310 - fixed public URL
            target.write_bytes(r.read())
        print(f"{f}: {target.stat().st_size // 1024} KB")


def cmd_build(base: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        split = f.removeprefix("ler_").removesuffix(".conll")
        with (base / f).open(encoding="utf-8") as fh:
            docs = build_docs(read_conll(fh), split)
        tmp = out / f"ler_{split}.jsonl"
        write_gold(docs, tmp)
        with tmp.open("rb") as src, gzip.open(out / f"ler_{split}.jsonl.gz", "wb", compresslevel=9) as dst:
            dst.write(src.read())
        tmp.unlink()
        counts = Counter(s.label for d in docs for s in d.spans)
        print(f"{split}: {len(docs)} docs, {dict(counts.most_common())}")


def load(data: Path, split: str) -> list[GoldDoc]:
    tmp = data / f".ler_{split}.jsonl"
    with gzip.open(data / f"ler_{split}.jsonl.gz", "rt", encoding="utf-8") as fh:
        tmp.write_text(fh.read(), encoding="utf-8")
    try:
        return read_gold(tmp)
    finally:
        tmp.unlink()


def cmd_eval(data: Path, split: str, limit: int | None, ner: bool) -> None:
    docs = load(data, split)[:limit] if limit else load(data, split)
    det = Detector(DetectorConfig(enable_ner=ner))
    strict, partial = [], []
    found = {k: [0, 0] for k in RULE_TYPES}  # label -> [found, total]
    az = [0, 0]
    fp_public: Counter = Counter()
    errors: list[str] = []
    t0 = time.perf_counter()
    for d in docs:
        dets = det.scan(d.text, "de").detections
        pred = [Span(x.start, x.end, TYPE_TO_LABEL[x.entity_type]) for x in dets if x.entity_type in TYPE_TO_LABEL]
        # Predictions on streets are left to the address recognizer, like in ner_dataset.
        pred = [p for p in pred if not any(g.label == "ADDR" and p.overlaps(g) for g in d.spans)]
        s, fps, fns = score_doc(d.spans, pred, partial=False)
        strict.append((d.key, s))
        s, fps, fns = score_doc(d.spans, pred, partial=True)
        partial.append((d.key, s))
        for g in d.spans:
            if g.label in RULE_TYPES:
                found[g.label][1] += 1
                if any(x.entity_type in RULE_TYPES[g.label] and g.start < x.end and x.start < g.end for x in dets):
                    found[g.label][0] += 1
            if g.label == "RS":
                for m in AZ.finditer(d.text, g.start, g.end):
                    az[1] += 1
                    if any(x.entity_type == "case_number" and x.start <= m.start() and m.end() <= x.end for x in dets):
                        az[0] += 1
                    elif len(errors) < 400:
                        errors.append(f"- missed case number `{m.group()}` in: {d.text[g.start:g.end][:160]}")
        public_fps = []
        for p in fps:
            hit = next((g.label for g in d.spans if g.label in PUBLIC_LABELS and p.overlaps(g)), None)
            if hit:
                fp_public[f"{p.label} on {hit}"] += 1
                public_fps.append((p, hit))
        for p, hit in public_fps[:3]:
            if len(errors) < 400:
                errors.append(f"- {p.label} on {hit}: `{d.text[p.start:p.end]}` in …{d.text[max(0, p.start - 60):p.end + 40]}…")
        for g in fns[:2]:
            if len(errors) < 400:
                errors.append(f"- missed {g.label}: `{d.text[g.start:g.end]}` in …{d.text[max(0, g.start - 60):g.end + 40]}…")
    rate = lambda a, b: round(a / b, 3) if b else None  # noqa: E731
    report = {
        "split": split, "docs": len(docs), "ner": ner, "seconds": round(time.perf_counter() - t0, 1),
        "entities_partial": summarize(partial), "entities_strict": summarize(strict),
        "public_references_found": {k: {"found": f, "total": n, "rate": rate(f, n)} for k, (f, n) in found.items()},
        "case_numbers_in_case_law": {"found": az[0], "total": az[1], "rate": rate(*az)},
        "false_positives_on_public_references": dict(fp_public.most_common()),
    }
    (data / f"eval_{split}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (data / f"errors_{split}.md").write_text(f"# Errors on LER {split} ({len(docs)} docs, NER {'on' if ner else 'off'})\n\n"
                                             + "\n".join(errors) + "\n", encoding="utf-8")
    p = report["entities_partial"]["micro"]
    print(json.dumps({"entities_partial": p, **{k: report[k] for k in (
        "public_references_found", "case_numbers_in_case_law", "false_positives_on_public_references")}},
        indent=1, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["download", "build", "eval"])
    ap.add_argument("--dir", type=Path, default=Path("local/ler"), help="raw CoNLL files (not committed)")
    ap.add_argument("--out", type=Path, default=Path("datasets/ler"))
    ap.add_argument("--data", type=Path, default=Path("datasets/ler"))
    ap.add_argument("--split", default="dev", choices=["train", "dev", "test"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-ner", action="store_true")
    a = ap.parse_args()
    if a.cmd == "download":
        cmd_download(a.dir)
    elif a.cmd == "build":
        cmd_build(a.dir, a.out)
    else:
        cmd_eval(a.data, a.split, a.limit, not a.no_ner)


if __name__ == "__main__":
    sys.exit(main())
