import json

from fastapi.testclient import TestClient

from cato.api import create_app
from cato.api.settings import Settings
from cato.leakcheck import check_text, mask, run

KEY = "cato_test_user_key_0123456789abcdef"


def test_generic_patterns_and_masking():
    hits = check_text("Mail an max@example.org, IBAN DE89 3704 0044 0532 0130 00, Bestellung 4711223, "
                      "Tel 0151 2345678", [])
    kinds = {k for k, _ in hits}
    assert {"email", "iban", "long_number", "phone"} <= kinds
    assert all("example.org" not in s and "3704" not in s for _, s in hits)
    assert mask("abcdef") == "ab**** (6 chars)"
    assert check_text("PERSON_001 bestellte ORDER_NUMBER_001 am 12.11.", []) == []


def test_known_values_reported_by_line_only():
    hits = check_text("Hallo Anna Müller", ["# comment-free list", "anna müller"])
    assert hits == [("known_value", "secrets line 2")]


def test_run_against_api(tmp_path):
    src = tmp_path / "c.jsonl"
    rows = [{"id": f"s{i}", "created_at": 1762905600 + i, "messages": [
        {"role": "user", "content": "Mein Name ist Max Mustermann, Bestellung 4711-2231, max@example.org"}]}
        for i in range(3)]
    src.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    app = create_app(Settings.from_env({
        "CATO_API_KEYS": KEY, "CATO_POLICY_DIR": str(tmp_path / "p"), "CATO_ACCOUNTS_DB": ":memory:",
        "CATO_AUDIT_DB": ":memory:", "CATO_TRACE_DB": ":memory:", "CATO_SOURCE": "jsonl",
        "CATO_SOURCE_PATH": str(src), "CATO_CONVERSATIONS_DB": ":memory:"}))
    client = TestClient(app)
    report = run(client, "http://testserver", KEY, limit=2, secrets=["Mustermann"])
    assert report.conversations == 2
    # Without a custom pattern the order number survives: exactly what the check is for.
    kinds = report.summary()["by_kind"]
    assert kinds.get("long_number") == 2 and "known_value" not in kinds and "email" not in kinds
    assert not any("4711" in f.sample for f in report.findings)
