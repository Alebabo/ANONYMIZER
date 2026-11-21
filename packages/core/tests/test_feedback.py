import json

from fastapi.testclient import TestClient

from anonymizer.api.app import create_app
from anonymizer.api.settings import Settings
from anonymizer.feedback import FeedbackError, FeedbackStore

KEY = "test_key_0123456789abcdef0123456789"
TEXT = "Rechtsanwalt Kowalski reicht beim LG Köln Klage ein, Az. 2 O 123/24. Kanzlei Vogt & Partner."


def _app(tmp_path):
    env = {"ANONYMIZER_API_KEYS": KEY, "ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL": "a@example.org",
           "ANONYMIZER_BOOTSTRAP_ADMIN_PASSWORD": "secret-password-1", "ANONYMIZER_ENABLE_NER": "0",
           "ANONYMIZER_POLICY_DIR": str(tmp_path / "policies")}
    for k in ("TRACE", "ACCOUNTS", "AUDIT", "PLAYGROUND", "FEEDBACK"):
        env[f"ANONYMIZER_{k}_DB"] = str(tmp_path / f"{k.lower()}.db")
    c = TestClient(create_app(Settings.from_env(env)))
    tok = c.post("/v1/auth/login", json={"email": "a@example.org", "password": "secret-password-1"}).json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}, {"Authorization": f"Bearer {KEY}"}


def span(text, value, kind, label=""):
    i = text.index(value)
    return {"start": i, "end": i + len(value), "kind": kind, "label": label}


def test_feedback_roundtrip_export_and_audit(tmp_path):
    c, admin, key = _app(tmp_path)
    spans = [span(TEXT, "Kowalski", "missed", "person"), span(TEXT, "Vogt & Partner", "missed", "organization"),
             span(TEXT, "Kanzlei", "wrong", "organization")]
    r = c.post("/v1/feedback", headers=key, json={"text": TEXT, "spans": spans, "policy": "banking-default"})
    assert r.status_code == 201 and r.json()["spans"] == 3

    assert c.get("/v1/feedback", headers=key).status_code == 403          # raw text: admins only
    rows = c.get("/v1/feedback", headers=admin).json()
    assert rows[0]["text"] == TEXT and rows[0]["policy"] == "banking-default"

    lines = c.get("/v1/feedback/export", headers=admin).text.splitlines()
    row = json.loads(lines[0])
    assert [(s["label"], s["text"]) for s in row["spans"]] == [("PER", "Kowalski"), ("ORG", "Vogt & Partner")]
    assert row["reject"] == [{"start": TEXT.index("Kanzlei"), "end": TEXT.index("Kanzlei") + 7, "text": "Kanzlei",
                              "was": "organization"}]

    audit = c.get("/v1/audit-logs?resource_type=feedback", headers=admin).json()["data"]
    assert {e["action"] for e in audit} == {"create", "export"}
    assert TEXT not in json.dumps(audit)                                   # the audit log never holds the text
    assert not any(TEXT in json.dumps(t) for t in c.get("/v1/traces", headers=admin).json())

    assert c.delete(f"/v1/feedback/{rows[0]['id']}", headers=admin).status_code == 204
    assert c.get("/v1/feedback", headers=admin).json() == []


def test_feedback_rejects_bad_spans(tmp_path):
    c, _, key = _app(tmp_path)
    bad = [
        [{"start": 0, "end": 999, "kind": "missed", "label": "person"}],   # outside the text
        [span(TEXT, "Kowalski", "missed", "spaceship")],                   # unknown type
        [],                                                                  # nothing marked
    ]
    for spans in bad:
        assert c.post("/v1/feedback", headers=key, json={"text": TEXT, "spans": spans}).status_code in (400, 422)


def test_store_validates_and_dedupes():
    s = FeedbackStore()
    row = s.add("org", "Max ruft an", [{"start": 0, "end": 3, "kind": "missed", "label": "person"}] * 2, "me")
    assert len(row["spans"]) == 1
    try:
        s.add("org", "Max", [{"start": 0, "end": 3, "kind": "maybe", "label": "person"}], "me")
        raise AssertionError("expected error")
    except FeedbackError:
        pass
