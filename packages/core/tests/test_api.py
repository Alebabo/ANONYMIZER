import json
import logging

import pytest
from fastapi.testclient import TestClient

from cato.api import create_app
from cato.api.settings import Settings, SettingsError
from cato.vault import VaultKey

API_KEY = "cato_test_user_key_0123456789abcdef"
ADMIN_KEY = "cato_test_admin_key_0123456789abcdef"
USER = {"Authorization": f"Bearer {API_KEY}"}
ADMIN = {"X-API-Key": ADMIN_KEY}

LETTER = ("Unser Mandant Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00, "
          "erreichbar unter max@example.org.")
SECRETS = ["Mustermann", "DE89 3704", "max@example.org"]


@pytest.fixture
def client(tmp_path):
    settings = Settings.from_env({
        "CATO_API_KEYS": API_KEY,
        "CATO_ADMIN_KEYS": ADMIN_KEY,
        "CATO_VAULT_KEY": VaultKey.generate().to_b64(),
        "CATO_VAULT_PATH": str(tmp_path / "vault.json"),
        "CATO_POLICY_DIR": str(tmp_path / "policies"),
        "CATO_MAX_CHARS": "5000",
        "CATO_ACCOUNTS_DB": ":memory:", "CATO_AUDIT_DB": ":memory:", "CATO_TRACE_DB": str(tmp_path / "traces.db"),
    })
    return TestClient(create_app(settings))


# --- settings ------------------------------------------------------------------

@pytest.mark.parametrize("env", [
    {"CATO_API_KEYS": "short"},
    {"CATO_BOOTSTRAP_ADMIN_EMAIL": "a@example.org"},
    {"CATO_API_KEYS": API_KEY, "CATO_ADMIN_KEYS": API_KEY},
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
    settings = Settings.from_env({"CATO_API_KEYS": API_KEY, "CATO_POLICY_DIR": str(tmp_path / "p"), "CATO_ACCOUNTS_DB": ":memory:", "CATO_AUDIT_DB": ":memory:", "CATO_TRACE_DB": ":memory:"})
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
    assert held["decision"]["policy"] == "legal-default@v1"
    local = client.post("/v1/protect", json={"text": "Herr Max Mustermann leidet an einer Depression.",
                                             "destination": "local"}, headers=USER).json()
    assert local["allowed"]


def test_protect_dry_run_returns_no_text(client):
    r = client.post("/v1/protect", json={"text": "Herr Max Mustermann bittet um Rückruf.", "dry_run": True},
                    headers=USER).json()
    assert r["allowed"] and r["text"] is None and r["decision"]["dry_run"]


def test_namespace_without_vault_is_rejected(tmp_path):
    settings = Settings.from_env({"CATO_API_KEYS": API_KEY, "CATO_POLICY_DIR": str(tmp_path / "p"), "CATO_ACCOUNTS_DB": ":memory:", "CATO_AUDIT_DB": ":memory:", "CATO_TRACE_DB": ":memory:"})
    c = TestClient(create_app(settings))
    r = c.post("/v1/anonymize", json={"text": LETTER, "namespace": "m"}, headers=USER)
    assert r.status_code == 400


# --- policies ------------------------------------------------------------------------------

def test_policy_management(client):
    names = [p["name"] for p in client.get("/v1/policies", headers=USER).json()]
    assert names == ["legal-default"]
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
