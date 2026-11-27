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
import re
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


# Labels that are not sensitive on their own (project owner, 27.11.2026): companies, public bodies, places, dates and
# times, amounts, bank and practice identifiers. Every other label (persons, private addresses, identifiers, account,
# card and contact data, date of birth, credentials) counts for the "sensitive recall", the >99 % target.
NOT_SENSITIVE = {"organization", "company", "public_body", "location", "date", "date_time", "time", "money", "bic",
                 "swift_bic_code", "bank_routing_number", "local_latlng", "de_bsnr"}


# smartdata and MobIE are news and traffic reports: their "addresses" are streets and roads, not where someone lives.
NOT_SENSITIVE_BY_SOURCE = {"smartdata": {"address"}, "mobie": {"address"}}


def is_sensitive(label: str, source: str = "") -> bool:
    return label.lower() not in NOT_SENSITIVE and label.lower() not in NOT_SENSITIVE_BY_SOURCE.get(source, ())


# Gold spans without personal data: placeholders of already anonymised texts ("X.________", "[Arbeitgebername]").
_PLACEHOLDER = re.compile(r"_{3,}|^\W*\[[^\]]*\]\W*$")
# Documents in another language or script (gheim has French, Thai, Arabic and Russian chunks marked de_ch, nym has
# Danish and Swedish texts) are not what a German anonymizer is measured on. Only clear cases are dropped: mostly
# non-Latin letters, or several foreign function words and fewer German ones; tables and short replies stay.
_DE_WORDS = {"der", "die", "das", "und", "ist", "nicht", "mit", "ein", "eine", "von", "zu", "den", "im", "für", "auf",
             "sich", "wurde", "hat", "dem", "des", "bei", "sie", "wir", "ich", "sind", "wird", "ihre", "ihr", "auch"}
_FOREIGN_WORDS = {"le", "la", "les", "du", "et", "est", "une", "pour", "dans", "que", "qui", "aux", "sur", "par", "avec",
                  "il", "di", "che", "per", "con", "della", "sono", "och", "att", "det", "ett", "som", "är", "og", "er",
                  "til", "jeg", "af", "het", "een", "ik", "niet", "zijn", "the", "and", "of", "to", "is", "for", "that",
                  "with", "are", "el", "los", "las", "por", "una", "não", "você"}


def is_german(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if letters and sum(not ("a" <= c.lower() <= "z" or c in "äöüßÄÖÜàâçéèêëîïôûùüÿñæøåóíúšžčćđłńśźż") for c in letters) > len(letters) * 0.3:
        return False
    words = re.findall(r"[^\W\d_]+", text.lower())
    de, foreign = sum(w in _DE_WORDS for w in words), sum(w in _FOREIGN_WORDS for w in words)
    return not (foreign >= 3 and foreign > 2 * de)


def print_report(report: dict) -> None:
    """Per source: masked recall, sensitive recall and precision bound, then the labels; at the end the sensitive
    recall over all sources together."""
    found = total = 0
    for src, r in report.items():
        print(f"{src}: {r['docs'] - r.get('skipped_docs', 0)} docs, masked recall {r['masked_recall']}, sensitive recall {r['sensitive_recall']}, "
              f"precision >= {r['masked_precision_lower_bound']}")
        for k, v in r["labels"].items():
            print(f"   {k:28} n={v['total']:5}  masked {v['masked']}  typed {v['typed']}")
        found += r["sensitive_found"]
        total += r["sensitive_total"]
    if total:
        print(f"all: sensitive recall {round(found / total, 4)} ({found}/{total}, missed {total - found})")


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
        skipped_docs = 0
        t0 = time.perf_counter()
        for key, text, gold in docs:
            if not is_german(text):
                skipped_docs += 1
                continue
            gold = [g for g in gold if not _PLACEHOLDER.search(text[g[0]:g[1]])]
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
        s_found = sum(v for k, v in masked.items() if is_sensitive(k, source))
        s_total = sum(v for k, v in total.items() if is_sensitive(k, source))
        report[source] = {
            "docs": len(docs), "seconds": round(time.perf_counter() - t0, 1),
            "masked_recall": r(sum(masked.values()), sum(total.values())),
            "sensitive_recall": r(s_found, s_total), "sensitive_found": s_found, "sensitive_total": s_total, "skipped_docs": skipped_docs,
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
    print_report(cmd_eval(a.data, sources, a.limit))


if __name__ == "__main__":
    sys.exit(main())
