"""Opt-in content traces: off by default, admins only when on."""
from fastapi.testclient import TestClient

from anonymizer.api import create_app
from anonymizer.api.settings import Settings

API_KEY = "anonymizer_test_user_key_0123456789abcdef"
ADMIN_KEY = "anonymizer_test_admin_key_0123456789abcdef"
USER = {"Authorization": f"Bearer {API_KEY}"}
ADMIN = {"X-API-Key": ADMIN_KEY}
LETTER = "Unser Mandant Herr Max Mustermann ist erreichbar unter max@example.org."


def _client(tmp_path, content: bool) -> TestClient:
    env = {"ANONYMIZER_API_KEYS": API_KEY, "ANONYMIZER_ADMIN_KEYS": ADMIN_KEY,
           "ANONYMIZER_POLICY_DIR": str(tmp_path / "policies"), "ANONYMIZER_ACCOUNTS_DB": ":memory:",
           "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": str(tmp_path / "traces.db")}
    if content:
        env["ANONYMIZER_TRACE_CONTENT"] = "1"
    return TestClient(create_app(Settings.from_env(env)))


def _protect(c: TestClient) -> str:
    r = c.post("/v1/protect", json={"text": LETTER, "destination": "external"}, headers=USER)
    assert r.status_code == 200
    return c.get("/v1/traces?limit=1", headers=ADMIN).json()[0]["id"]


def test_content_not_stored_by_default(tmp_path):
    c = _client(tmp_path, content=False)
    tid = _protect(c)
    trace = c.get(f"/v1/traces/{tid}", headers=ADMIN).json()
    assert trace["content"] == []
    assert "Mustermann" not in (tmp_path / "traces.db").read_bytes().decode("utf-8", "ignore")


def test_content_stored_when_enabled_and_admin_only(tmp_path):
    c = _client(tmp_path, content=True)
    tid = _protect(c)
    trace = c.get(f"/v1/traces/{tid}", headers=ADMIN).json()
    [item] = trace["content"]
    assert "max@example.org" not in item["output"]
    originals = {r["original"] for r in item["replacements"]}
    assert "max@example.org" in originals
    assert any("Mustermann" in o for o in originals)
    assert c.get(f"/v1/traces/{tid}", headers=USER).json()["content"] == []
    assert all(t["content"] == [] for t in c.get("/v1/traces", headers=USER).json())


def test_metrics_dashboard_fields():
    from anonymizer.tracing import Trace, TraceStore

    store = TraceStore()
    store.add(Trace(route="/v1/playground", upstream="playground", tool="query_dataset", outcome="allow", entity_counts={"person": 2},
                    fields={"$.name": {"person": 2}}, latency_ms=10, resource="c1"))
    store.add(Trace(route="/v1/protect", outcome="block", latency_ms=30, needs_review=True))
    store.add(Trace(route="/v1/protect", outcome="allow", status=502, warnings=["x"]))
    m = store.metrics(24)
    assert m["needs_review"] == 1 and m["with_warnings"] == 1 and m["resources_read"] == 1
    assert m["top_fields"] == {"$.name": 2}
    ops = {o["name"]: o for o in m["by_operation"]}
    assert ops["playground__query_dataset"]["entities"] == 2 and ops["/v1/protect"]["errors"] == 1
    last = m["timeseries"][-1]
    assert (last["anonymized"], last["not_allowed"], last["errors"], last["clean"]) == (1, 1, 1, 0)
    assert m["previous"]["requests"] == 0 and m["last_trace_at"] is not None
    assert m["latency_ms"]["p50"] == 10 and m["latency_ms"]["p95"] == 30
