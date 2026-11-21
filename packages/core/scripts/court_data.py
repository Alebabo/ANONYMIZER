"""Full court decisions (Open Legal Data) with synthetic values in place of the court's anonymization.

    python packages/core/scripts/court_data.py download [--dir local/courts] [--per-jurisdiction 400]
    python packages/core/scripts/court_data.py contexts [--dir local/courts]      # which "…" placeholders exist
    python packages/core/scripts/court_data.py build    [--dir local/courts] [--out datasets/courts]
    python packages/core/scripts/court_data.py eval     [--data datasets/courts] [--split dev]

Source: https://de.openlegaldata.io (API, no key). Decisions are official works (§ 5 UrhG); the Open Legal Data
database is ODbL 1.0, so datasets/courts is published under ODbL 1.0 as well (see THIRD_PARTY_NOTICES.md).

Unlike German LER these are whole decisions from local and regional courts, with the parts where personal data
really sits: rubrum, parties, witnesses, addresses. The courts replace those values by "…" (or "...", "X",
"A."). build fills each placeholder whose context says what it was ("Herr …", "…straße 5", "in …", "… GmbH")
with a synthetic value and records its span; see anonymizer.courts.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from anonymizer.courts import build_doc, clean_html, placeholder_contexts, split_of
from anonymizer.ner_dataset import GoldDoc, Span, read_gold, write_gold

API = "https://de.openlegaldata.io/api/cases/"
# (filter, value, share of --per): local and regional courts are what a law firm handles most.
SAMPLES = [
    ("court__level_of_appeal", "Amtsgericht", 1.5), ("court__level_of_appeal", "Landgericht", 1.75),
    ("court__level_of_appeal", "Oberlandesgericht", 1.25), ("court__jurisdiction", "Arbeitsgerichtsbarkeit", 0.75),
    ("court__jurisdiction", "Verwaltungsgerichtsbarkeit", 0.75), ("court__jurisdiction", "Sozialgerichtsbarkeit", 0.5),
]
UA = "OpenAnonymizer-dataset-builder/0.1 (research; low rate)"


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed public API
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or attempt == 5:
                raise
            # 429: the API asks us to slow down; honour Retry-After, else wait a minute or more.
            wait = int(exc.headers.get("Retry-After") or 0) or (60 * (attempt + 1) if exc.code == 429 else 2 ** attempt * 2)
            time.sleep(wait)
        except Exception:  # noqa: BLE001 - retry network errors with backoff
            if attempt == 5:
                raise
            time.sleep(2 ** attempt * 2)
    raise RuntimeError("unreachable")


def cmd_download(base: Path, per: int, delay: float, workers: int = 3) -> None:
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    raw = base / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    def fetch(case_id: int) -> None:
        path = raw / f"{case_id}.json"
        if path.exists():
            return
        try:
            case = get(f"{API}{case_id}/?format=json")
        except Exception as exc:  # noqa: BLE001 - skip one case, keep the run going
            print(f"skip {case_id}: {exc}", flush=True)
            return
        path.write_text(json.dumps({k: case.get(k) for k in (
            "id", "court", "file_number", "date", "type", "ecli", "content")}, ensure_ascii=False), encoding="utf-8")
        time.sleep(delay)

    for key, value, share in SAMPLES:
        want, ids, page = int(per * share), [], 1
        while len(ids) < want:
            q = urllib.parse.urlencode({"format": "json", "page_size": 100, "page": page, key: value})
            try:
                listing = get(f"{API}?{q}")
            except urllib.error.HTTPError:  # past the last page
                break
            ids += [h["id"] for h in listing["results"] if not h["court"]["name"].startswith(("Bundes", "Europä"))]
            if not listing.get("next"):
                break
            page += 1
        ids = ids[:want]
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(fetch, ids))
        print(f"{value}: {len(ids)}", flush=True)


def load_raw(base: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((base / "raw").glob("*.json"))]


def cmd_contexts(base: Path) -> None:
    c: Counter = Counter()
    for case in load_raw(base):
        c.update(placeholder_contexts(clean_html(case.get("content") or "")))
    for ctx, n in c.most_common(80):
        print(f"{n:6d}  {ctx}")


def cmd_build(base: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    splits: dict[str, list[GoldDoc]] = {"train": [], "dev": [], "test": []}
    kinds: Counter = Counter()
    for case in load_raw(base):
        text = clean_html(case.get("content") or "")
        if len(text) < 500:
            continue
        split = split_of(case["id"])
        doc = build_doc(case, text, split)
        if doc is None:
            continue
        kinds.update(s.label for s in doc.spans)
        splits[split].append(doc)
    for split, docs in splits.items():
        tmp = out / f"courts_{split}.jsonl"
        write_gold(docs, tmp)
        with tmp.open("rb") as src, gzip.open(out / f"courts_{split}.jsonl.gz", "wb", compresslevel=9) as dst:
            dst.write(src.read())
        tmp.unlink()
        print(f"{split}: {len(docs)} decisions, {sum(len(d.spans) for d in docs)} spans")
    print(dict(kinds.most_common()))


def load(data: Path, split: str) -> list[GoldDoc]:
    tmp = data / f".courts_{split}.jsonl"
    with gzip.open(data / f"courts_{split}.jsonl.gz", "rt", encoding="utf-8") as fh:
        tmp.write_text(fh.read(), encoding="utf-8")
    try:
        return read_gold(tmp)
    finally:
        tmp.unlink()


def cmd_eval(data: Path, split: str, limit: int | None) -> None:
    """Recall on the inserted values (the only ones we know for sure) and false positives on public references
    found by the rules. Other capitalised words are unknown (the court may have left a name), so precision on
    them is not scored here; LER measures precision."""
    from anonymizer.detect import Detector  # noqa: PLC0415

    docs = load(data, split)[:limit] if limit else load(data, split)
    det = Detector()
    want = {"PER": {"person"}, "ORG": {"organization"}, "LOC": {"location", "address"}, "ADDR": {"address"},
            "DATE": {"date", "date_of_birth"}, "AZ": {"case_number"}, "IBAN": {"iban"}}
    hit: Counter = Counter()
    total: Counter = Counter()
    missed: list[str] = []
    t0 = time.perf_counter()
    for d in docs:
        dets = det.scan(d.text, "de").detections
        for g in d.spans:
            total[g.label] += 1
            ok = any(x.entity_type in want[g.label] and x.start <= g.start and g.end <= x.end for x in dets)
            hit[g.label] += ok
            if not ok and len(missed) < 300:
                missed.append(f"- {g.label} `{d.text[g.start:g.end]}` in …{d.text[max(0, g.start - 70):g.end + 40]}…")
    report = {"split": split, "docs": len(docs), "seconds": round(time.perf_counter() - t0, 1),
              "recall": {k: {"found": hit[k], "total": total[k], "rate": round(hit[k] / total[k], 3) if total[k] else None}
                         for k in sorted(total)},
              "recall_all": round(sum(hit.values()) / max(1, sum(total.values())), 3)}
    (data / f"eval_{split}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (data / f"errors_{split}.md").write_text(f"# Missed on courts {split}\n\n" + "\n".join(missed) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["download", "contexts", "build", "eval"])
    ap.add_argument("--dir", type=Path, default=Path("local/courts"))
    ap.add_argument("--out", type=Path, default=Path("datasets/courts"))
    ap.add_argument("--data", type=Path, default=Path("datasets/courts"))
    ap.add_argument("--split", default="dev", choices=["train", "dev", "test"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--per-jurisdiction", type=int, default=400)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between API calls")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    if a.cmd == "download":
        cmd_download(a.dir, a.per_jurisdiction, a.delay, a.workers)
    elif a.cmd == "contexts":
        cmd_contexts(a.dir)
    elif a.cmd == "build":
        cmd_build(a.dir, a.out)
    else:
        cmd_eval(a.data, a.split, a.limit)


if __name__ == "__main__":
    sys.exit(main())
