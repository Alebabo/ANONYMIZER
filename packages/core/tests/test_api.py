import json
import logging

import pytest
from fastapi.testclient import TestClient

from anonymizer.api import create_app
from anonymizer.api.settings import Settings, SettingsError
from anonymizer.vault import VaultKey

API_KEY = "anonymizer_test_user_key_0123456789abcdef"
ADMIN_KEY = "anonymizer_test_admin_key_0123456789abcdef"
USER = {"Authorization": f"Bearer {API_KEY}"}
ADMIN = {"X-API-Key": ADMIN_KEY}

LETTER = ("Unser Mandant Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00, "
          "erreichbar unter max@example.org.")
SECRETS = ["Mustermann", "DE89 3704", "max@example.org"]


@pytest.fixture
def client(tmp_path):
    settings = Settings.from_env({
        "ANONYMIZER_API_KEYS": API_KEY,
        "ANONYMIZER_ADMIN_KEYS": ADMIN_KEY,
        "ANONYMIZER_VAULT_KEY": VaultKey.generate().to_b64(),
        "ANONYMIZER_VAULT_PATH": str(tmp_path / "vault.json"),
        "ANONYMIZER_POLICY_DIR": str(tmp_path / "policies"),
        "ANONYMIZER_MAX_CHARS": "5000",
        "ANONYMIZER_ACCOUNTS_DB": ":memory:", "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": str(tmp_path / "traces.db"),
    })
    return TestClient(create_app(settings))


# --- settings ------------------------------------------------------------------

@pytest.mark.parametrize("env", [
    {"ANONYMIZER_API_KEYS": "short"},
    {"ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL": "a@example.org"},
    {"ANONYMIZER_API_KEYS": API_KEY, "ANONYMIZER_ADMIN_KEYS": API_KEY},
])
def test_settings_fail_closed(env):
    with pytest.raises(SettingsError):
        Settings.from_env(env)


# --- auth ------------------------------------------------------------------------

def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/v1/scan", "/v1/classify", "/v1/anonymize", "/v1/protect"])
def test_endpoints_require_key(client, path):
    assert client.post(path, json={"text": "x"}).status_code == 401
    assert client.post(path, json={"text": "x"}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_admin_endpoints_reject_user_key(client):
    assert client.post("/v1/restore", json={"text": "PERSON_001", "namespace": "m"}, headers=USER).status_code == 403
    assert client.post("/v1/policies", json={"yaml": "name: x"}, headers=USER).status_code == 403


def test_admin_key_can_use_user_endpoints(client):
    assert client.post("/v1/scan", json={"text": "Herr Max Mustermann"}, headers=ADMIN).status_code == 200


def test_admin_disabled_without_admin_keys(tmp_path):
    settings = Settings.from_env({"ANONYMIZER_API_KEYS": API_KEY, "ANONYMIZER_POLICY_DIR": str(tmp_path / "p"), "ANONYMIZER_ACCOUNTS_DB": ":memory:", "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": ":memory:"})
    c = TestClient(create_app(settings))
    r = c.post("/v1/restore", json={"text": "x", "namespace": "m"}, headers=USER)
    assert r.status_code == 403 and "disabled" in r.json()["detail"]


# --- endpoints -------------------------------------------------------------------------

def test_scan_returns_offsets_not_values(client):
    r = client.post("/v1/scan", json={"text": LETTER, "language": "de"}, headers=USER)
    assert r.status_code == 200
    body = r.json()
    types = {d["entity_type"] for d in body["detections"]}
    assert {"person", "iban", "email"} <= types
    for d in body["detections"]:
        assert "text" not in d
        assert LETTER[d["start"]:d["end"]]  # offsets usable by the client
    assert not any(s in r.text for s in SECRETS)
    assert r.headers["X-Request-ID"].startswith("req_")


def test_classify(client):
    r = client.post("/v1/classify", json={"text": LETTER}, headers=USER)
    assert r.status_code == 200 and r.json()["risk"] == "critical"
    assert not any(s in r.text for s in SECRETS)


def test_anonymize_and_restore_roundtrip(client):
    r = client.post("/v1/anonymize", json={"text": LETTER, "namespace": "matter-1", "include_role": True},
                    headers=USER)
    assert r.status_code == 200
    body = r.json()
    assert body["reversible"] and "PERSON_001 (Mandant)" in body["text"]
    assert not any(s in r.text for s in SECRETS)
    back = client.post("/v1/restore", json={"text": "PERSON_001 und PERSON_404", "namespace": "matter-1"},
                       headers=ADMIN).json()
    assert back["text"] == "Max Mustermann und PERSON_404" and back["unresolved"] == ["PERSON_404"]


def test_anonymize_custom_methods(client):
    r = client.post("/v1/anonymize", json={"text": LETTER, "methods": {"iban": "mask"}}, headers=USER)
    assert "DE89 **** **** **** **30 00" in r.json()["text"]


def test_protect_allowed_and_blocked(client):
    ok = client.post("/v1/protect", json={"text": "Herr Max Mustermann bittet um Rückruf."}, headers=USER).json()
    assert ok["allowed"] and ok["outcome"] == "allow" and "Mustermann" not in ok["text"]
    held = client.post("/v1/protect", json={"text": "Herr Max Mustermann leidet an einer Depression."},
                       headers=USER).json()
    assert not held["allowed"] and held["text"] is None and held["outcome"] == "local_only"
    assert held["decision"]["policy"] == "banking-default@v1"
    local = client.post("/v1/protect", json={"text": "Herr Max Mustermann leidet an einer Depression.",
                                             "destination": "local"}, headers=USER).json()
    assert local["allowed"]


def test_protect_dry_run_returns_no_text(client):
    r = client.post("/v1/protect", json={"text": "Herr Max Mustermann bittet um Rückruf.", "dry_run": True},
                    headers=USER).json()
    assert r["allowed"] and r["text"] is None and r["decision"]["dry_run"]


def test_protect_output_text_only(client):
    r = client.post("/v1/protect", json={"text": "Herr Max Mustermann bittet um Rückruf.", "output": "text"},
                    headers=USER)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith("Herr ") and "Mustermann" not in r.text and r.headers["X-Trace-Id"]
    held = client.post("/v1/protect", json={"text": "Herr Max Mustermann leidet an einer Depression.",
                                            "output": "text"}, headers=USER)
    assert held.status_code == 403 and "local_only" in held.text and "Mustermann" not in held.text
    both = client.post("/v1/protect", json={"text": "Herr Max Mustermann.", "output": "text", "dry_run": True},
                       headers=USER)
    assert both.status_code == 400


def test_namespace_without_vault_is_rejected(tmp_path):
    settings = Settings.from_env({"ANONYMIZER_API_KEYS": API_KEY, "ANONYMIZER_POLICY_DIR": str(tmp_path / "p"), "ANONYMIZER_ACCOUNTS_DB": ":memory:", "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": ":memory:"})
    c = TestClient(create_app(settings))
    r = c.post("/v1/anonymize", json={"text": LETTER, "namespace": "m"}, headers=USER)
    assert r.status_code == 400


# --- policies ------------------------------------------------------------------------------

def test_policy_management(client):
    names = [p["name"] for p in client.get("/v1/policies", headers=USER).json()]
    assert names == ["banking-default", "legal-default", "support-default"]
    yaml_v1 = "name: strict\nversion: 1\ndocument_rules:\n  - {min_risk: critical, action: block}\ndefault_action: redact\n"
    created = client.post("/v1/policies", json={"yaml": yaml_v1}, headers=ADMIN)
    assert created.status_code == 201 and created.json()["hash"].startswith("sha256:")
    assert client.post("/v1/policies", json={"yaml": yaml_v1}, headers=ADMIN).status_code == 400  # immutable
    bad = client.post("/v1/policies", json={"yaml": "name: x\nrules:\n  - {action: nope}\n"}, headers=ADMIN)
    assert bad.status_code == 422
    assert client.get("/v1/policies/strict", headers=USER).json()["version"] == 1
    assert [h["version"] for h in client.get("/v1/policies/strict/history", headers=USER).json()] == [1]
    blocked = client.post("/v1/protect", json={"text": LETTER, "policy": "strict"}, headers=USER).json()
    assert blocked["outcome"] == "block" and blocked["text"] is None


def test_policy_dry_run_diff(client):
    candidate = "name: candidate\nrules:\n  - {entity: iban, action: block}\ndefault_action: redact\n"
    r = client.post("/v1/policies/dry-run", json={"text": LETTER, "candidate_yaml": candidate}, headers=USER)
    assert r.status_code == 200
    body = r.json()
    assert body["outcome_after"] == "block"
    assert any(c["entity_type"] == "iban" and c["after"] == "block" for c in body["changes"])
    assert body["text_before"] and "Mustermann" not in body["text_before"]  # protected sample, live policy
    assert body["text_after"] is None and body["reasons_after"]              # blocked: nothing would be sent


def test_policy_dry_run_preview_leaves_the_vault_alone(client):
    candidate = "name: candidate\nrules:\n  - {entity: person, action: pseudonymize}\ndefault_action: redact\n"
    body = client.post("/v1/policies/dry-run", json={"text": "Herr Max Mustermann ruft an.", "candidate_yaml": candidate},
                       headers=USER).json()
    assert "PERSON_" in body["text_after"]
    restored = client.post("/v1/restore", json={"text": body["text_after"], "namespace": "dry-run"}, headers=ADMIN).json()
    assert restored["restored"] == 0


# Own policy without review_uncertain, so the result does not depend on whether the spaCy model is installed.
SAMPLE = "Bitte IBAN DE89 3704 0044 0532 0130 00 prüfen, Rückfragen an max@example.org."
TEST_POLICY = ("name: sample-test\nrules:\n  - {id: contact, entity: [email], action: pseudonymize}\n"
               "  - {id: accounts, entity: [iban], action: redact}\ndefault_action: redact\nreview_uncertain: false\n")


@pytest.fixture
def sample_policy(client):
    assert client.post("/v1/policies", json={"yaml": TEST_POLICY}, headers=ADMIN).status_code == 201
    return "/v1/policies/sample-test/test"


def test_policy_test_endpoint_without_changes(client, sample_policy):
    body = client.post(sample_policy, json={"text": SAMPLE}, headers=USER).json()
    assert body["policy"] == "sample-test@v1"
    assert body["text_before"] == body["text_after"] and body["changes"] == []
    assert "DE89 3704" not in body["text_after"] and "max@example.org" not in body["text_after"]
    assert body["entities"].get("iban") == 1


def test_policy_test_endpoint_with_unsaved_changes(client, sample_policy):
    before = client.get("/v1/policies/sample-test", headers=USER).json()["version"]
    body = client.post(sample_policy,
                       json={"text": SAMPLE, "changes": {"email": "allow", "iban": "block"}}, headers=USER).json()
    assert body["outcome_after"] == "block" and body["text_after"] is None
    assert any(c["entity_type"] == "iban" and c["after"] == "block" for c in body["changes"])
    assert client.get("/v1/policies/sample-test", headers=USER).json()["version"] == before  # nothing saved


def test_policy_test_endpoint_rejects_bad_input(client, sample_policy):
    assert client.post(sample_policy, json={"text": SAMPLE, "changes": {"email": "nope"}},
                       headers=USER).status_code == 422
    assert client.post("/v1/policies/missing/test", json={"text": SAMPLE}, headers=USER).status_code == 400
    assert client.post(sample_policy, json={"text": SAMPLE}).status_code == 401


# --- leak protection -------------------------------------------------------------------------

def test_validation_errors_do_not_echo_input(client):
    r = client.post("/v1/scan", json={"text": LETTER, "language": "fr"}, headers=USER)
    assert r.status_code == 422
    assert not any(s in r.text for s in SECRETS)
    r = client.post("/v1/scan", json={"text": LETTER, "unexpected": LETTER}, headers=USER)
    assert r.status_code == 422 and "Mustermann" not in r.text


def test_size_limit(client):
    r = client.post("/v1/scan", json={"text": "a" * 5001}, headers=USER)
    assert r.status_code == 413


def test_logs_contain_no_request_content(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.post("/v1/protect", json={"text": LETTER, "namespace": "matter-1"}, headers=USER)
    client.post("/v1/restore", json={"text": "PERSON_001", "namespace": "matter-1"}, headers=ADMIN)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "/v1/protect" in logged
    for s in SECRETS + ["matter-1", API_KEY, ADMIN_KEY]:
        assert s not in logged


def test_openapi_schema_available(client):
    spec = client.get("/openapi.json").json()
    assert {"/v1/scan", "/v1/classify", "/v1/anonymize", "/v1/protect", "/v1/restore", "/v1/policies"} <= set(spec["paths"])


def test_info(client):
    body = client.get("/v1/info", headers=USER).json()
    assert body["vault"] and body["admin_endpoints"] and body["ner"] in {"available", "unavailable"}
    assert json.dumps(body).find(API_KEY) == -1


# --- hardening ---------------------------------------------------------------------

def test_dry_run_writes_nothing_to_the_vault(client):
    body = {"text": LETTER, "namespace": "matter-9", "dry_run": True}
    assert client.post("/v1/protect", json=body, headers=USER).json()["text"] is None
    restored = client.post("/v1/restore", json={"text": "PERSON_001", "namespace": "matter-9"}, headers=ADMIN).json()
    assert restored["restored"] == 0 and restored["unresolved"] == ["PERSON_001"]


def test_oversized_body_is_refused_before_auth_and_parsing(client):
    r = client.post("/v1/scan", content=b"x" * 600_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_request_id_is_sanitized(client):
    ok = client.get("/health", headers={"X-Request-ID": "trace-42.a:b"})
    assert ok.headers["X-Request-ID"] == "trace-42.a:b"
    bad = client.get("/health", headers={"X-Request-ID": "x" * 200})
    assert bad.headers["X-Request-ID"].startswith("req_")
    spaced = client.get("/health", headers={"X-Request-ID": "a b forged=1"})
    assert spaced.headers["X-Request-ID"].startswith("req_")


def test_malformed_policy_yaml_is_a_client_error(client):
    r = client.post("/v1/policies", json={"yaml": "name: p\nrules: [oops\n"}, headers=ADMIN)
    assert r.status_code == 400 and "oops" not in r.text
    r = client.post("/v1/policies/dry-run", json={"text": LETTER, "candidate_yaml": "name: [\n"}, headers=USER)
    assert r.status_code == 400


def test_every_model_call_is_traced_with_channel_and_actor(client):
    client.post("/v1/scan", json={"text": SAMPLE}, headers=USER)
    client.post("/v1/anonymize", json={"text": SAMPLE}, headers=USER)
    r = client.post("/v1/protect", json={"text": SAMPLE}, headers=USER).json()
    assert r["trace_id"]
    traces = client.get("/v1/traces?client=api", headers=USER).json()
    assert {t["route"] for t in traces} >= {"/v1/scan", "/v1/anonymize", "/v1/protect"}
    assert all(t["client"] == "api" and t["actor"] for t in traces)
    scan = next(t for t in traces if t["route"] == "/v1/scan")
    assert scan["entity_counts"] == {"iban": 1, "email": 1}
    assert client.get("/v1/traces?client=mcp", headers=USER).json() == []


def test_mcp_anonymize_uses_the_saved_policy_and_writes_a_full_trace(tmp_path):
    from anonymizer.mcp import AnonymizerTools, MCPConfig
    from anonymizer.policy import Policy
    from anonymizer.tracing import TraceStore

    traces = TraceStore(tmp_path / "t.db")
    current = {"p": Policy.from_yaml(TEST_POLICY)}
    tools = AnonymizerTools(MCPConfig(), traces=traces, policy_provider=lambda: current["p"])
    out = tools.anonymize_content(SAMPLE)
    assert "max@example.org" not in out["text"] and "EMAIL_" in out["text"]
    current["p"] = Policy.from_yaml(TEST_POLICY.replace("action: pseudonymize", "action: allow"))
    assert "max@example.org" in tools.anonymize_content(SAMPLE)["text"]  # policy change applies right away
    t = traces.list(client="mcp")[0]
    assert t.tool == "anonymize_content" and t.policy == "sample-test@v1" and t.entity_counts == {"iban": 1, "email": 1}
