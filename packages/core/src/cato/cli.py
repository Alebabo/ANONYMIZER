"""Command line: ``cato scan | classify | anonymize | restore | eval``."""

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
    cl = sub.add_parser("classify", help="detect and classify; prints risk per entity and document")
    cl.add_argument("path", help="file path or '-' for stdin")
    cl.add_argument("--language", choices=["de", "en"])
    cl.add_argument("--config", help="classifier YAML config")
    an = sub.add_parser("anonymize", help="detect and anonymize; prints the transformed text")
    an.add_argument("path", help="file path or '-' for stdin")
    an.add_argument("--language", choices=["de", "en"])
    an.add_argument("--vault", help="vault file for reversible pseudonyms (key from CATO_VAULT_KEY)")
    an.add_argument("--namespace", help="vault namespace, e.g. a matter id (required with --vault)")
    an.add_argument("--json", action="store_true", help="print result metadata as JSON")
    rs = sub.add_parser("restore", help="resolve placeholders using the vault (authorised use only)")
    rs.add_argument("path", help="file path or '-' for stdin")
    rs.add_argument("--vault", required=True)
    rs.add_argument("--namespace", required=True)
    ev = sub.add_parser("eval", help="evaluate detection against a YAML corpus directory")
    ev.add_argument("corpus", help="directory with *.yaml documents")
    args = parser.parse_args(argv)

    if args.command == "eval":
        return _eval(args.corpus)
    if args.command == "classify":
        return _classify(args)
    if args.command == "anonymize":
        return _anonymize(args)
    if args.command == "restore":
        return _restore(args)

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


def _classify(args: argparse.Namespace) -> int:
    from cato.classify import Classifier, ClassifierConfig

    text = sys.stdin.read() if args.path == "-" else open(args.path, encoding="utf-8").read()
    config = ClassifierConfig.from_yaml(args.config) if args.config else None
    result = Detector().scan(text, args.language)
    doc = Classifier(config).classify_text(text, result)
    json.dump(doc.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _read(path: str) -> str:
    return sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()


def _anonymize(args: argparse.Namespace) -> int:
    from cato.anonymize import Anonymizer
    from cato.vault import FileVault, VaultKey

    text = _read(args.path)
    vault = FileVault(args.vault, VaultKey.from_env()) if args.vault else None
    result = Anonymizer(vault=vault).anonymize(text, Detector().scan(text, args.language), namespace=args.namespace)
    if args.json:
        json.dump(result.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(result.text)
    return 0


def _restore(args: argparse.Namespace) -> int:
    from cato.anonymize import restore
    from cato.vault import FileVault, VaultKey

    result = restore(_read(args.path), FileVault(args.vault, VaultKey.from_env()), args.namespace)
    sys.stdout.write(result.text)
    if result.unresolved:
        print(f"\nunresolved placeholders: {', '.join(result.unresolved)}", file=sys.stderr)
    return 0


def _eval(directory: str) -> int:
    from pathlib import Path

    from cato.evaluation import evaluate_doc, load_corpus, summarize

    reports = [evaluate_doc(doc, Detector()) for doc in load_corpus(Path(directory))]
    for r in reports:
        status = "ok" if r.ok else "FAIL"
        risk = r.classification.risk.value if r.classification else "-"
        print(f"{status:4} {r.id}: risk={risk} missed={len(r.missed)} fp={len(r.false_positives)} "
              f"unlabelled={len(r.unlabelled)}")
        if r.wrong_document_risk:
            print(f"     document risk expected {r.wrong_document_risk[0]}, got {r.wrong_document_risk[1]}")
        for spec, got in r.wrong_risk:
            print(f"     risk {spec} -> got {got}")
        for spec in r.missed:
            print(f"     missed {spec}")
        for spec, det in r.false_positives:
            print(f"     false positive {det.entity_type} for rule {spec}")
    print(json.dumps(summarize(reports), indent=2))
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
