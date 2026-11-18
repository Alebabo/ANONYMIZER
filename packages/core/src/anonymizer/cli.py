"""Command line: ``anonymizer scan | classify | anonymize | restore | protect | policy-validate | eval``
plus account management: ``anonymizer org create | org list | user create | user list | seed-demo``."""

from __future__ import annotations

import argparse
import os
import json
import sys

from anonymizer.detect import Detector, DetectorConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anonymizer")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="detect sensitive data in a text file")
    scan.add_argument("path", help="file path or '-' for stdin")
    scan.add_argument("--language", choices=["de", "en"])
    scan.add_argument("--no-ner", action="store_true", help="rules only, skip spaCy NER (misses bare names)")
    scan.add_argument("--ner", action="store_true", help=argparse.SUPPRESS)  # former opt-in, now the default
    scan.add_argument("--show-values", action="store_true", help="include raw values in the output")
    cl = sub.add_parser("classify", help="detect and classify; prints risk per entity and document")
    cl.add_argument("path", help="file path or '-' for stdin")
    cl.add_argument("--language", choices=["de", "en"])
    cl.add_argument("--config", help="classifier YAML config")
    an = sub.add_parser("anonymize", help="detect and anonymize; prints the transformed text")
    an.add_argument("path", help="file path or '-' for stdin")
    an.add_argument("--language", choices=["de", "en"])
    an.add_argument("--vault", help="vault file for reversible pseudonyms (key from ANONYMIZER_VAULT_KEY)")
    an.add_argument("--namespace", help="vault namespace, e.g. a matter id (required with --vault)")
    an.add_argument("--json", action="store_true", help="print result metadata as JSON")
    rs = sub.add_parser("restore", help="resolve placeholders using the vault (authorised use only)")
    rs.add_argument("path", help="file path or '-' for stdin")
    rs.add_argument("--vault", required=True)
    rs.add_argument("--namespace", required=True)
    pr = sub.add_parser("protect", help="full pipeline: detect, classify, apply policy, anonymize")
    pr.add_argument("path", help="file path or '-' for stdin")
    pr.add_argument("--policy", help="policy YAML (default: built-in legal-default)")
    pr.add_argument("--destination", choices=["external", "local"], default="external")
    pr.add_argument("--language", choices=["de", "en"])
    pr.add_argument("--dry-run", action="store_true", help="evaluate and report without returning text")
    pv = sub.add_parser("policy-validate", help="validate a policy YAML file")
    pv.add_argument("path")
    ev = sub.add_parser("eval", help="evaluate detection against a YAML corpus directory")
    ev.add_argument("corpus", help="directory with *.yaml documents")
    org = sub.add_parser("org", help="manage organizations (accounts DB from ANONYMIZER_ACCOUNTS_DB)")
    org_sub = org.add_subparsers(dest="org_command", required=True)
    oc = org_sub.add_parser("create", help="create an organization")
    oc.add_argument("name")
    oc.add_argument("--id", help="organization id (default: random)")
    org_sub.add_parser("list", help="list organizations")
    us = sub.add_parser("user", help="manage dashboard users")
    us_sub = us.add_subparsers(dest="user_command", required=True)
    uc = us_sub.add_parser("create", help="create a user (password is prompted or read from stdin)")
    uc.add_argument("--email", required=True)
    uc.add_argument("--name")
    uc.add_argument("--org", default="default", help="organization id (default: default)")
    uc.add_argument("--role", choices=["admin", "member"], default="admin")
    uc.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    ul = us_sub.add_parser("list", help="list users of an organization")
    ul.add_argument("--org", default="default")
    sc = sub.add_parser("source-check", help="check the conversation source from ANONYMIZER_SOURCE_* (no content printed)")
    sc.add_argument("--protect", action="store_true",
                    help="also run the newest conversation through the policy and print counts only")
    lc = sub.add_parser("leak-check", help="read conversations through a running API and report anything "
                                           "that should not be in protected output (values are masked)")
    lc.add_argument("--api", default=os.environ.get("ANONYMIZER_BASE_URL", "http://127.0.0.1:8080"))
    lc.add_argument("--key", default=os.environ.get("ANONYMIZER_API_KEY"), help="OpenAnonymizer API key (or ANONYMIZER_API_KEY)")
    lc.add_argument("--limit", type=int, default=50, help="conversations to read (counts against the quota)")
    lc.add_argument("--secrets", help="file with known real values, one per line (never printed)")
    lc.add_argument("--details", action="store_true", help="list every finding (masked)")
    sd = sub.add_parser("seed-demo", help="write synthetic demo traces (metadata only) for an organization")
    sd.add_argument("--org", default="default")
    sd.add_argument("--count", type=int, default=400)
    sd.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    if args.command in ("org", "user", "seed-demo"):
        return _accounts(args)
    if args.command == "eval":
        return _eval(args.corpus)
    if args.command == "leak-check":
        return _leak_check(args)
    if args.command == "source-check":
        return _source_check(args.protect)
    if args.command == "classify":
        return _classify(args)
    if args.command == "anonymize":
        return _anonymize(args)
    if args.command == "restore":
        return _restore(args)
    if args.command == "protect":
        return _protect(args)
    if args.command == "policy-validate":
        return _policy_validate(args.path)

    text = _read(args.path)
    result = Detector(DetectorConfig(enable_ner=not args.no_ner)).scan(text, args.language)
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
    from anonymizer.classify import Classifier, ClassifierConfig

    text = _read(args.path)
    config = ClassifierConfig.from_yaml(args.config) if args.config else None
    result = Detector().scan(text, args.language)
    doc = Classifier(config).classify_text(text, result)
    json.dump(doc.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _anonymize(args: argparse.Namespace) -> int:
    from anonymizer.anonymize import OpenAnonymizer
    from anonymizer.vault import FileVault, VaultKey

    text = _read(args.path)
    vault = FileVault(args.vault, VaultKey.from_env()) if args.vault else None
    result = OpenAnonymizer(vault=vault).anonymize(text, Detector().scan(text, args.language), namespace=args.namespace)
    if args.json:
        json.dump(result.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(result.text)
    return 0


def _restore(args: argparse.Namespace) -> int:
    from anonymizer.anonymize import restore
    from anonymizer.vault import FileVault, VaultKey

    result = restore(_read(args.path), FileVault(args.vault, VaultKey.from_env()), args.namespace)
    sys.stdout.write(result.text)
    if result.unresolved:
        print(f"\nunresolved placeholders: {', '.join(result.unresolved)}", file=sys.stderr)
    return 0


def _protect(args: argparse.Namespace) -> int:
    from anonymizer.pipeline import Pipeline
    from anonymizer.policy import Policy

    policy = Policy.from_file(args.policy) if args.policy else None
    result = Pipeline(policy).protect(_read(args.path), args.destination, language=args.language,
                                      dry_run=args.dry_run)
    out = {
        "outcome": result.decision.outcome.value,
        "policy": result.decision.policy,
        "policy_hash": result.decision.policy_hash,
        "risk": result.classification.risk.value,
        "reasons": result.decision.reasons,
        "text": None if args.dry_run else result.text,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result.allowed else 2


def _policy_validate(path: str) -> int:
    from anonymizer.policy import Policy

    try:
        policy = Policy.from_file(path)
    except ValueError as exc:  # pydantic.ValidationError and PolicyError (malformed YAML)
        print(exc, file=sys.stderr)
        return 1
    print(f"ok {policy.ref} {policy.content_hash} rules={len(policy.rules)} document_rules={len(policy.document_rules)}")
    return 0


def _eval(directory: str) -> int:
    from pathlib import Path

    from anonymizer.evaluation import evaluate_doc, load_corpus, summarize

    from anonymizer.detect import load_custom_patterns

    # Same patterns as the API, so the evaluation measures what will run.
    custom = load_custom_patterns(os.environ["ANONYMIZER_CUSTOM_PATTERNS"]) if os.environ.get("ANONYMIZER_CUSTOM_PATTERNS") else []
    detector = Detector(DetectorConfig(custom_entities=custom))
    reports = [evaluate_doc(doc, detector) for doc in load_corpus(Path(directory))]
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


def _leak_check(args: argparse.Namespace) -> int:
    import httpx

    from anonymizer.leakcheck import load_secrets, run

    if not args.key:
        print("--key or ANONYMIZER_API_KEY is required", file=sys.stderr)
        return 2
    secrets = load_secrets(args.secrets) if args.secrets else []
    with httpx.Client(timeout=120) as client:
        report = run(client, args.api, args.key, args.limit, secrets)
    out = report.summary()
    if args.details:
        out["details"] = [f.__dict__ for f in report.findings]
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if report.ok else 1


def _source_check(protect: bool) -> int:
    """Connectivity and shape check for the configured source. Prints counts and ids' shape, never content."""
    import os

    from anonymizer.conversations import ConversationError
    from anonymizer.sources import SourceError, source_from_env

    try:
        source = source_from_env()
        if source is None:
            print("ANONYMIZER_SOURCE is not set", file=sys.stderr)
            return 2
        page = source.list(limit=20)
        out: dict = {**source.describe(), "listed": len(page.data), "more": page.next_cursor is not None,
                     "with_prompt": sum(1 for h in page.data if h.prompt),
                     "with_tags": sum(1 for h in page.data if h.tags)}
        if page.data:
            conv = source.get(page.data[0].id)
            out["newest_messages"] = len(conv.messages)
            out["roles"] = sorted({m.role for m in conv.messages})
            if protect:
                from anonymizer.classify import Classifier
                from anonymizer.conversations import ConversationConfig, ConversationService, ConversationStore
                from anonymizer.detect import DetectorConfig, load_custom_patterns
                from anonymizer.pipeline import Pipeline
                from anonymizer.policy import builtin_policy

                custom = load_custom_patterns(os.environ["ANONYMIZER_CUSTOM_PATTERNS"]) \
                    if os.environ.get("ANONYMIZER_CUSTOM_PATTERNS") else []
                detector = Detector(DetectorConfig(custom_entities=custom))
                policy = builtin_policy(os.environ.get("ANONYMIZER_CONVERSATIONS_POLICY", "support-default"))
                svc = ConversationService(source, lambda v: Pipeline(policy, detector=detector,
                                                                    classifier=Classifier(), vault=v),
                                          ConversationStore(), ConversationConfig.from_env(dict(os.environ)))
                from anonymizer.conversations import LOCAL_PRINCIPAL

                # Counts only: a dropped label may be personal data, so its value is never printed.
                raw = [t for h in page.data for t in h.tags[:20]]
                raw += [x for m in conv.messages for x in (m.agent, m.action, m.subtopic) if x]
                kept = sum(1 for x in raw if svc._safe_label(x))
                out["labels"] = {"checked": len(raw), "dropped": len(raw) - kept,
                                 "allow_listed": len(svc.config.known_labels)}

                cid = svc.list(LOCAL_PRINCIPAL, limit=1)["data"][0]["id"]
                result = svc.get(LOCAL_PRINCIPAL, cid)
                out["protected"] = {"outcome": result["outcome"], "risk": result["risk"],
                                    "withheld": result["withheld"]}
    except (SourceError, ConversationError) as exc:
        print(f"source error: {exc}", file=sys.stderr)
        return 1
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _accounts(args: argparse.Namespace) -> int:
    import getpass
    import os

    from anonymizer.accounts import AccountError, AccountStore
    from anonymizer.audit import AuditLog

    accounts = AccountStore(os.environ.get("ANONYMIZER_ACCOUNTS_DB", "data/accounts.db"))
    audit = AuditLog(os.environ.get("ANONYMIZER_AUDIT_DB", "data/audit.db"))
    try:
        if args.command == "org" and args.org_command == "create":
            o = accounts.create_org(args.name, args.id)
            audit.record(o["id"], "create", "organization", o["id"], after=o, actor_label="system (cli)")
            print(o["id"])
        elif args.command == "org":
            for o in accounts.list_orgs():
                print(f"{o['id']}\t{o['name']}")
        elif args.command == "user" and args.user_command == "create":
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\n")
            else:
                password = getpass.getpass("Password (min. 12 characters): ")
                if getpass.getpass("Repeat password: ") != password:
                    print("error: passwords do not match", file=sys.stderr)
                    return 1
            u = accounts.create_user(args.org, args.email, args.name or args.email.split("@")[0], password, args.role)
            audit.record(args.org, "create", "member", u["id"], after=u, actor_label="system (cli)")
            print(f"{u['id']}\t{u['email']}\t{u['role']}")
        elif args.command == "user":
            for u in accounts.list_users(args.org):
                print(f"{u['id']}\t{u['email']}\t{u['role']}" + ("\tdisabled" if u["disabled"] else ""))
        else:
            from anonymizer.demo import seed_traces
            from anonymizer.tracing import TraceStore

            accounts.get_org(args.org)
            store = TraceStore(os.environ.get("ANONYMIZER_TRACE_DB", "data/traces.db"))
            n = seed_traces(store, args.org, args.count, args.days)
            audit.record(args.org, "seed", "demo_data", "traces", after={"traces": n, "days": args.days},
                         actor_label="system (cli)")
            print(f"{n} demo traces written to organization {args.org}")
    except AccountError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
