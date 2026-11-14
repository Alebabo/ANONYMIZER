"""Command line: ``cato scan <file|->`` (JSON, raw values hidden unless --show-values) and ``cato eval <dir>``."""

from __future__ import annotations

import argparse
import json
import sys

from cato.detect import Detector, DetectorConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cato")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="detect sensitive data in a text file")
    scan.add_argument("path", help="file path or '-' for stdin")
    scan.add_argument("--language", choices=["de", "en"])
    scan.add_argument("--ner", action="store_true", help="enable spaCy NER (requires cato-core[ner])")
    scan.add_argument("--show-values", action="store_true", help="include raw values in the output")
    ev = sub.add_parser("eval", help="evaluate detection against a YAML corpus directory")
    ev.add_argument("corpus", help="directory with *.yaml documents")
    args = parser.parse_args(argv)

    if args.command == "eval":
        return _eval(args.corpus)

    text = sys.stdin.read() if args.path == "-" else open(args.path, encoding="utf-8").read()
    result = Detector(DetectorConfig(enable_ner=args.ner)).scan(text, args.language)
    out = {
        "language": result.language,
        "signals": sorted(result.document_signals),
        "warnings": result.warnings,
        "detections": [d.model_dump(mode="json") if args.show_values else d.redacted() for d in result.detections],
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def _eval(directory: str) -> int:
    from pathlib import Path

    from cato.evaluation import evaluate_doc, load_corpus, summarize

    reports = [evaluate_doc(doc, Detector()) for doc in load_corpus(Path(directory))]
    for r in reports:
        status = "ok" if r.ok else "FAIL"
        print(f"{status:4} {r.id}: missed={len(r.missed)} fp={len(r.false_positives)} unlabelled={len(r.unlabelled)}")
        for spec in r.missed:
            print(f"     missed {spec}")
        for spec, det in r.false_positives:
            print(f"     false positive {det.entity_type} for rule {spec}")
    print(json.dumps(summarize(reports), indent=2))
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
