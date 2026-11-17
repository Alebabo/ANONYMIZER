import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from anonymizer.accounts import AccountError, AccountStore, hash_password, verify_password
from anonymizer.api import create_app
from anonymizer.api.settings import Settings
from anonymizer.audit import AuditLog
from anonymizer.cli import main as cli
from anonymizer.vault import VaultKey

ADMIN_KEY = "anonymizer_test_admin_key_0123456789abcdef"
PW = "correct horse battery"
LETTER = "Unser Mandant Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00."


@pytest.fixture
def env(tmp_path):
    return {
        "ANONYMIZER_ADMIN_KEYS": ADMIN_KEY,
        "ANONYMIZER_VAULT_KEY": VaultKey.generate().to_b64(),
        "ANONYMIZER_VAULT_PATH": str(tmp_path / "vault.json"),
        "ANONYMIZER_POLICY_DIR": str(tmp_path / "policies"),
        "ANONYMIZER_TRACE_DB": str(tmp_path / "traces.db"),
        "ANONYMIZER_ACCOUNTS_DB": str(tmp_path / "accounts.db"),
        "ANONYMIZER_AUDIT_DB": str(tmp_path / "audit.db"),
        "ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL": "admin@example.org",
        "ANONYMIZER_BOOTSTRAP_ADMIN_PASSWORD": PW,
    }


@pytest.fixture
def client(env):
    return TestClient(create_app(Settings.from_env(env)))


def login(client, email="admin@example.org", password=PW):
    r = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# --- unit -----------------------------------------------------------------------

def test_password_hashing():
    h = hash_password(PW)
    assert h.startswith("scrypt$") and PW not in h
    assert verify_password(PW, h) and not verify_password(PW + "x", h)
    assert not verify_password(PW, "garbage")
    with pytest.raises(AccountError):
        hash_password("short")


def test_store_keeps_only_hashes(tmp_path):
    store = AccountStore(tmp_path / "a.db")
    store.create_user("default", "a@example.org", "A", PW, "admin")
    key, _ = store.create_api_key("default", "ci", "user", None)
    token, _ = store.create_session(store.user_by_email("a@example.org")["id"])
    raw = (tmp_path / "a.db").read_bytes()
    for secret in (PW, key, token):
        assert secret.encode() not in raw


def test_env_keys_optional_but_no_access(tmp_path):
    s = Settings.from_env({"ANONYMIZER_POLICY_DIR": str(tmp_path / "p"), "ANONYMIZER_TRACE_DB": ":memory:",
                           "ANONYMIZER_ACCOUNTS_DB": ":memory:", "ANONYMIZER_AUDIT_DB": ":memory:"})
    c = TestClient(create_app(s))
    assert c.post("/v1/scan", json={"text": "x"}).status_code == 401
    assert c.post("/v1/scan", json={"text": "x"}, headers={"Authorization": "Bearer anonymizer_whatever"}).status_code == 401


# --- login ---------------------------------------------------------------------------

def test_login_me_logout(client):
    h = login(client)
    me = client.get("/v1/auth/me", headers=h).json()
    assert me["kind"] == "session" and me["role"] == "admin"
    assert me["user"]["email"] == "admin@example.org" and "password_hash" not in me["user"]
    assert me["organization"]["id"] == "default"
    assert client.post("/v1/auth/logout", headers=h).status_code == 204
    assert client.get("/v1/auth/me", headers=h).status_code == 401


def test_login_failures_are_uniform_and_rate_limited(client):
    r1 = client.post("/v1/auth/login", json={"email": "admin@example.org", "password": "wrong-password"})
    r2 = client.post("/v1/auth/login", json={"email": "nobody@example.org", "password": "wrong-password"})
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()
    for _ in range(9):
        client.post("/v1/auth/login", json={"email": "admin@example.org", "password": "wrong-password"})
    r = client.post("/v1/auth/login", json={"email": "admin@example.org", "password": PW})
    assert r.status_code == 429


def test_login_error_does_not_echo_password(client):
    r = client.post("/v1/auth/login", json={"email": "x", "password": "secret-pass", "extra": 1})
    assert r.status_code == 422 and "secret-pass" not in r.text


def test_password_change_signs_out_other_sessions(client):
    h1, h2 = login(client), login(client)
    new = "another long password"
    r = client.post("/v1/auth/password", headers=h1, json={"current_password": PW, "new_password": new})
    assert r.status_code == 204
    assert client.get("/v1/auth/me", headers=h1).status_code == 200
    assert client.get("/v1/auth/me", headers=h2).status_code == 401
    login(client, password=new)
    r = client.post("/v1/auth/password", headers=h1, json={"current_password": "nope", "new_password": new})
    assert r.status_code == 400


# --- roles & members -------------------------------------------------------------------

def test_member_is_read_only(client):
    h = login(client)
    r = client.post("/v1/members", headers=h, json={"email": "m@example.org", "name": "M", "password": PW})
    assert r.status_code == 201 and r.json()["role"] == "member"
    m = login(client, "m@example.org")
    assert client.get("/v1/api-keys", headers=m).status_code == 200
    assert client.post("/v1/api-keys", headers=m, json={"name": "x"}).status_code == 403
    assert client.patch("/v1/organization", headers=m, json={"name": "x"}).status_code == 403
    assert client.get("/v1/audit-logs", headers=m).status_code == 403


def test_last_admin_and_self_demotion_are_refused(client):
    h = login(client)
    me = client.get("/v1/auth/me", headers=h).json()["user"]
    r = client.patch(f"/v1/members/{me['id']}", headers=h, json={"role": "member"})
    assert r.status_code == 400 and "own admin" in r.json()["detail"]


def test_disabled_member_loses_sessions(client):
    h = login(client)
    uid = client.post("/v1/members", headers=h, json={"email": "m@example.org", "name": "M", "password": PW}).json()["id"]
    m = login(client, "m@example.org")
    assert client.patch(f"/v1/members/{uid}", headers=h, json={"disabled": True}).json()["disabled"] is True
    assert client.get("/v1/auth/me", headers=m).status_code == 401
    assert client.post("/v1/auth/login", json={"email": "m@example.org", "password": PW}).status_code == 401


# --- API keys --------------------------------------------------------------------------------

def test_api_key_lifecycle(client):
    h = login(client)
    created = client.post("/v1/api-keys", headers=h, json={"name": "backend", "role": "user"}).json()
    key = created["key"]
    assert key.startswith("anonymizer_") and created["prefix"] == key[:12]
    k = {"Authorization": f"Bearer {key}"}
    assert client.post("/v1/scan", headers=k, json={"text": "Herr Max Mustermann"}).status_code == 200
    listed = client.get("/v1/api-keys", headers=h).json()
    assert all("key" not in x and "key_hash" not in x for x in listed)
    assert listed[0]["last_used_at"] is not None
    assert client.delete(f"/v1/api-keys/{created['id']}", headers=h).json()["revoked_at"]
    assert client.post("/v1/scan", headers=k, json={"text": "x"}).status_code == 401


def test_dashboard_admin_cannot_restore(client):
    h = login(client)
    r = client.post("/v1/restore", headers=h, json={"text": "PERSON_001", "namespace": "m"})
    assert r.status_code == 403 and "admin API key" in r.json()["detail"]


# --- organization isolation ----------------------------------------------------------------------

@pytest.fixture
def two_orgs(env, client):
    store = AccountStore(env["ANONYMIZER_ACCOUNTS_DB"])
    store.create_org("Firm B", "firm-b")
    store.create_user("firm-b", "b@example.org", "B", PW, "admin")
    return login(client), login(client, "b@example.org")


def test_traces_keys_members_are_scoped(client, two_orgs):
    a, b = two_orgs
    client.post("/v1/protect", headers=a, json={"text": LETTER})
    trace_id = client.get("/v1/traces", headers=a).json()[0]["id"]
    assert client.get("/v1/traces", headers=b).json() == []
    assert client.get(f"/v1/traces/{trace_id}", headers=b).status_code == 404
    assert client.get("/v1/metrics", headers=b).json()["requests"] == 0
    key_id = client.post("/v1/api-keys", headers=a, json={"name": "a"}).json()["id"]
    assert client.delete(f"/v1/api-keys/{key_id}", headers=b).status_code == 404
    assert [m["email"] for m in client.get("/v1/members", headers=b).json()] == ["b@example.org"]
    assert all(e["org_id"] == "firm-b" for e in client.get("/v1/audit-logs", headers=b).json()["data"])


def test_vault_namespaces_are_isolated_per_org(client, two_orgs):
    a, b = two_orgs
    key_b = client.post("/v1/api-keys", headers=b, json={"name": "adm", "role": "admin"}).json()["key"]
    kb = {"Authorization": f"Bearer {key_b}"}
    ka = {"X-API-Key": ADMIN_KEY}  # default org
    out = client.post("/v1/anonymize", headers=ka, json={"text": LETTER, "namespace": "matter-1"}).json()["text"]
    assert "Mustermann" not in out
    assert "Mustermann" in client.post("/v1/restore", headers=ka, json={"text": out, "namespace": "matter-1"}).json()["text"]
    r = client.post("/v1/restore", headers=kb, json={"text": out, "namespace": "matter-1"}).json()
    assert "Mustermann" not in r["text"] and r["restored"] == 0
    forged = client.post("/v1/restore", headers=ka, json={"text": out, "namespace": "firm-b\x1fmatter-1"})
    assert forged.status_code == 422


def test_only_default_org_writes_policies(client, two_orgs):
    _, b = two_orgs
    r = client.post("/v1/policies", headers=b, json={"yaml": "name: legal-default\nversion: 2\nrules: []\n"})
    assert r.status_code == 403


# --- audit log ---------------------------------------------------------------------------------------

def test_audit_records_security_events_without_secrets(client):
    h = login(client)
    client.post("/v1/auth/login", json={"email": "admin@example.org", "password": "wrong-password"})
    key = client.post("/v1/api-keys", headers=h, json={"name": "ci"}).json()
    client.delete(f"/v1/api-keys/{key['id']}", headers=h)
    client.patch("/v1/organization", headers=h, json={"name": "Kanzlei A"})
    ka = {"X-API-Key": ADMIN_KEY}
    out = client.post("/v1/anonymize", headers=ka, json={"text": LETTER, "namespace": "m1"}).json()["text"]
    client.post("/v1/restore", headers=ka, json={"text": out, "namespace": "m1"})
    page = client.get("/v1/audit-logs", headers=h, params={"limit": 100}).json()
    events = [(e["resource_type"], e["action"]) for e in page["data"]]
    for ev in [("member", "create"), ("session", "login"), ("session", "login_failed"), ("api_key", "create"),
               ("api_key", "revoke"), ("organization", "update"), ("vault", "restore")]:
        assert ev in events, ev
    blob = json.dumps(page)
    for secret in (PW, "wrong-password", key["key"], "Mustermann", "DE89"):
        assert secret not in blob
    restore = next(e for e in page["data"] if e["action"] == "restore")
    assert restore["actor_type"] == "api_key" and restore["after"]["restored"] >= 1
    failed = next(e for e in page["data"] if e["action"] == "login_failed")
    assert failed["actor_type"] == "anonymous" and failed["actor_id"] is None
    org = next(e for e in page["data"] if e["resource_type"] == "organization")
    assert org["before"]["name"] == "Default" and org["after"]["name"] == "Kanzlei A"
    assert set(page["actions"]) >= {"login", "create"}


def test_audit_pagination_and_filters(client):
    h = login(client)
    for i in range(5):
        client.post("/v1/api-keys", headers=h, json={"name": f"k{i}"})
    p1 = client.get("/v1/audit-logs", headers=h, params={"limit": 3, "resource_type": "api_key"}).json()
    assert len(p1["data"]) == 3 and p1["next_before"]
    p2 = client.get("/v1/audit-logs", headers=h, params={"limit": 3, "resource_type": "api_key",
                                                        "before": p1["next_before"]}).json()
    assert len(p2["data"]) == 2 and p2["next_before"] is None
    assert {e["id"] for e in p1["data"]}.isdisjoint(e["id"] for e in p2["data"])
    one = client.get(f"/v1/audit-logs/{p2['data'][0]['id']}", headers=h)
    assert one.status_code == 200 and one.json()["resource_type"] == "api_key"


def test_audit_chain_detects_tampering(env, client):
    h = login(client)
    client.post("/v1/api-keys", headers=h, json={"name": "k"})
    v = client.get("/v1/audit-logs/verify", headers=h).json()
    assert v["ok"] and v["entries"] >= 3
    db = sqlite3.connect(env["ANONYMIZER_AUDIT_DB"])
    db.execute("UPDATE audit_logs SET actor_label = 'someone else' WHERE action = 'login'")
    db.commit()
    v = client.get("/v1/audit-logs/verify", headers=h).json()
    assert not v["ok"] and v["broken_at"]


def test_audit_log_has_no_mutation_api():
    assert not any(hasattr(AuditLog, m) for m in ("update", "delete", "purge"))


# --- gateway status, retention, CLI -----------------------------------------------------------------

def test_gateway_status_hides_credentials(env):
    env = {**env, "ANONYMIZER_UPSTREAM_URL": "https://user:pw@api.example.com/v1", "ANONYMIZER_UPSTREAM_KEY": "sk-secret"}
    c = TestClient(create_app(Settings.from_env(env)))
    body = c.get("/v1/gateway", headers=login(c)).json()
    assert body["external"] == {"host": "https://api.example.com", "provider": "openai", "model": None,
                                "authenticated": True}
    assert "sk-secret" not in json.dumps(body) and "pw@" not in json.dumps(body)


def test_org_retention_is_applied(env, client):
    from anonymizer.tracing import Trace, TraceStore

    h = login(client)
    client.patch("/v1/organization", headers=h, json={"trace_retention_days": 1})
    store = TraceStore(env["ANONYMIZER_TRACE_DB"], 30, retention_for=lambda o: 1 if o == "default" else None)
    import time
    store.add(Trace(route="/old", created_at=time.time() - 3 * 86400), "default")
    store.add(Trace(route="/old", created_at=time.time() - 3 * 86400), "other")
    store.purge()
    assert store.list(org_id="default") == [] and len(store.list(org_id="other")) == 1


def test_cli_org_user_and_seed(env, monkeypatch, capsys):
    for k in ("ANONYMIZER_ACCOUNTS_DB", "ANONYMIZER_AUDIT_DB", "ANONYMIZER_TRACE_DB"):
        monkeypatch.setenv(k, env[k])
    assert cli(["org", "create", "Kanzlei C", "--id", "firm-c"]) == 0
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(PW + "\n"))
    assert cli(["user", "create", "--email", "c@example.org", "--org", "firm-c", "--password-stdin"]) == 0
    assert cli(["seed-demo", "--org", "firm-c", "--count", "50"]) == 0
    assert cli(["user", "create", "--email", "bad", "--org", "firm-c", "--password-stdin"]) == 1
    c = TestClient(create_app(Settings.from_env(env)))
    h = login(c, "c@example.org")
    assert c.get("/v1/metrics", headers=h, params={"hours": 24 * 8}).json()["requests"] == 50
    assert ("demo_data", "seed") in [(e["resource_type"], e["action"])
                                     for e in c.get("/v1/audit-logs", headers=h).json()["data"]]
