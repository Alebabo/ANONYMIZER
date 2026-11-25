"""German financial and banking texts with labelled personal data: measure the detector.

    python packages/core/scripts/finance_data.py download   # Gretel parquet files (not committed, see below)
    python packages/core/scripts/finance_data.py eval [--data datasets/finance] [--source all] [--limit N]

Sources (all synthetic, Apache-2.0, raw copies in datasets/finance/raw/, see datasets/finance/README.md):
  gretel       gretelai/synthetic_pii_finance_multilingual, German part: bank and finance documents (MT940,
               BAI, ISDA, statements, loan and insurance papers, support logs). Test split. Not committed: its
               synthetic API keys and tokens trip GitHub push protection; `download` fetches the German files.
  syntriq      syntriq/german-pii-benchmark: 687 documents of 26 types (Schufa, Lohnabrechnung, …) with
               check-digit-valid IBANs, tax ids, social security numbers.
  easyoctopus  EasyOctopus/german-support-pii-data: short German support messages with IBAN, BIC, cards,
               customer, order and account ids. Test split.

Reported per source and label: "masked" = share of gold values that any detection overlaps (would be hidden),
"typed" = share found with the matching OpenAnonymizer type, plus masked precision (share of detections that
overlap a gold value; the gold sets are not exhaustive, so this is a lower bound).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# Source label -> OpenAnonymizer entity types that count as the right type. Labels without a type of ours
# (passwords, API keys, IP addresses, …) are scored as "masked" only.
TYPE_MAP: dict[str, set[str]] = {
    **dict.fromkeys(["name", "first_name", "last_name", "PERSON"], {"person"}),
    **dict.fromkeys(["company", "ORGANIZATION"], {"organization"}),
    **dict.fromkeys(["street_address", "ADDRESS"], {"address", "location"}),
    **dict.fromkeys(["email", "EMAIL_ADDRESS", "EMAIL"], {"email"}),
    **dict.fromkeys(["phone_number", "PHONE_NUMBER", "PHONE"], {"phone"}),
    **dict.fromkeys(["date", "date_time"], {"date", "date_of_birth"}),
    **dict.fromkeys(["date_of_birth", "DATE_OF_BIRTH"], {"date_of_birth", "date"}),
    **dict.fromkeys(["iban", "IBAN_CODE", "IBAN"], {"iban"}),
    **dict.fromkeys(["swift_bic_code", "BIC"], {"bic"}),
    **dict.fromkeys(["credit_card_number", "CREDIT_CARD", "PAYMENT_CARD"], {"credit_card"}),
    **dict.fromkeys(["DE_TAX_ID", "TAX_ID"], {"tax_id", "tax_number"}),
    **dict.fromkeys(["DE_TAX_NUMBER"], {"tax_number", "tax_id"}),
    **dict.fromkeys(["ssn", "DE_SOCIAL_SECURITY"], {"social_security_number"}),
    **dict.fromkeys(["customer_id", "CUSTOMER_ID"], {"customer_number"}),
}


GRETEL = "https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual/resolve/main/data"


def cmd_download(data: Path) -> None:
    import urllib.request  # noqa: PLC0415

    target = data / "raw" / "gretel"
    target.mkdir(parents=True, exist_ok=True)
    for split in ("train", "test"):
        path = target / f"German_{split}.parquet"
        if not path.exists():
            urllib.request.urlretrieve(f"{GRETEL}/German_{split}-00000-of-00001.parquet", path)  # noqa: S310
        print(f"{path}: {path.stat().st_size // 1024} KB")


def load(data: Path, source: str) -> list[tuple[str, str, list[tuple[int, int, str]]]]:
    """(key, text, [(start, end, label)]) per document."""
    raw = data / "raw"
    out = []
    if source == "gretel":
        import pyarrow.parquet as pq  # noqa: PLC0415

        for i, r in enumerate(pq.read_table(raw / "gretel" / "German_test.parquet").to_pylist()):
            spans = [(s["start"], s["end"], s["label"]) for s in json.loads(r["pii_spans"])]
            out.append((f"gretel:{i}", r["generated_text"], spans))
    elif source == "syntriq":
        with gzip.open(raw / "syntriq" / "test.jsonl.gz", "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                out.append((f"syntriq:{r['id']}", r["text"], [(e["start"], e["end"], e["label"]) for e in r["entities"]]))
    elif source == "easyoctopus":
        with gzip.open(raw / "easyoctopus" / "test.jsonl.gz", "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                out.append((f"easyoctopus:{r['id']}", r["text"], [(g["start"], g["end"], g["label"]) for g in r["gold"]]))
    else:
        raise ValueError(source)
    return out


def cmd_eval(data: Path, sources: list[str], limit: int | None, load_fn=None, type_map=None,
             title: str = "finance") -> dict:
    """``load_fn``, ``type_map``, ``title``: other datasets in the same format (public_pii.py)."""
    load_fn, type_map = load_fn or load, type_map or TYPE_MAP
    from anonymizer.detect import Detector  # noqa: PLC0415

    det = Detector()
    report: dict = {}
    misses: list[str] = []
    for source in sources:
        docs = load_fn(data, source)[:limit] if limit else load_fn(data, source)
        total, masked, typed = Counter(), Counter(), Counter()
        n_pred = n_pred_hit = 0
        t0 = time.perf_counter()
        for key, text, gold in docs:
            dets = det.scan(text, "de").detections
            n_pred += len(dets)
            n_pred_hit += sum(any(d.start < e and s < d.end for s, e, _ in gold) for d in dets)
            for s, e, label in gold:
                total[label] += 1
                over = [d for d in dets if d.start < e and s < d.end]
                masked[label] += bool(over)
                if label in type_map and any(d.entity_type in type_map[label] for d in over):
                    typed[label] += 1
                if not over and len(misses) < 400:
                    misses.append(f"- {source} {label} `{text[s:e]}` in …{text[max(0, s - 60):e + 30]}…".replace("\n", " "))
        r = lambda a, b: round(a / b, 3) if b else None  # noqa: E731
        report[source] = {
            "docs": len(docs), "seconds": round(time.perf_counter() - t0, 1),
            "masked_recall": r(sum(masked.values()), sum(total.values())),
            "masked_precision_lower_bound": r(n_pred_hit, n_pred),
            "labels": {k: {"total": total[k], "masked": r(masked[k], total[k]),
                           "typed": r(typed[k], total[k]) if k in type_map else None}
                       for k, _ in total.most_common()},
        }
    (data / "eval.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (data / "errors.md").write_text(f"# Missed values ({title})\n\n" + "\n".join(misses) + "\n", encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["download", "eval"])
    ap.add_argument("--data", type=Path, default=Path("datasets/finance"))
    ap.add_argument("--source", default="all", choices=["all", "gretel", "syntriq", "easyoctopus"])
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    if a.cmd == "download":
        cmd_download(a.data)
        return
    sources = ["gretel", "syntriq", "easyoctopus"] if a.source == "all" else [a.source]
    if "gretel" in sources and not (a.data / "raw" / "gretel" / "German_test.parquet").exists():
        print("gretel: not downloaded, skipped (run: finance_data.py download)")
        sources = [s for s in sources if s != "gretel"] or sys.exit(0)
    report = cmd_eval(a.data, sources, a.limit)
    for src, r in report.items():
        print(f"{src}: {r['docs']} docs, masked recall {r['masked_recall']}, precision >= {r['masked_precision_lower_bound']}")
        for k, v in r["labels"].items():
            print(f"   {k:28} n={v['total']:5}  masked {v['masked']}  typed {v['typed']}")


if __name__ == "__main__":
    sys.exit(main())
