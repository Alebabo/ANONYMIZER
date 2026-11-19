import json

import httpx
import pytest
from fastapi.testclient import TestClient

from anonymizer.api import create_app
from anonymizer.api.settings import Settings

KEY = "anonymizer_test_user_key_0123456789abcdef"
H = {"Authorization": f"Bearer {KEY}"}


class FakeProvider:
    """Records what reaches the provider and answers with a configurable reply."""

    def __init__(self, reply=None, status=200):
        self.requests: list[dict] = []
        self.reply = reply or (lambda body: "Antwort an PERSON_001: Ihr Anliegen wird bearbeitet.")
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "boom", "code": "server_error"}})
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": self.reply(body)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })


def make_client(tmp_path, provider: FakeProvider, local: bool = False, restore: bool = True):
    env = {
        "ANONYMIZER_API_KEYS": KEY, "ANONYMIZER_POLICY_DIR": str(tmp_path / "p"), "ANONYMIZER_ACCOUNTS_DB": ":memory:", "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": ":memory:",
        "ANONYMIZER_UPSTREAM_URL": "https://api.provider.test/v1", "ANONYMIZER_UPSTREAM_KEY": "sk-upstream-secret",
        "ANONYMIZER_UPSTREAM_PROVIDER": "openai",
    }
    if local:
        env |= {"ANONYMIZER_LOCAL_UPSTREAM_URL": "http://ollama.local/v1", "ANONYMIZER_LOCAL_MODEL": "llama3.1"}
    if not restore:
        env["ANONYMIZER_GATEWAY_RESTORE"] = "0"
    return TestClient(create_app(Settings.from_env(env), gateway_transport=httpx.MockTransport(provider.handler)))


def chat(client, *contents, **extra):
    messages = [{"role": "system", "content": "Du bist ein juristischer Assistent."}]
    messages += [{"role": "user", "content": c} for c in contents]
    return client.post("/v1/chat/completions", headers=H, json={"model": "gpt-4o", "messages": messages, **extra})


def test_messages_are_protected_before_reaching_provider_and_restored(tmp_path):
    provider = FakeProvider()
    c = make_client(tmp_path, provider)
    r = chat(c, "Unser Mandant Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00, fragt nach dem Stand.")
    assert r.status_code == 200
    sent = json.dumps(provider.requests[0]["body"], ensure_ascii=False)
    assert "Mustermann" not in sent and "DE89" not in sent and "PERSON_001" in sent
    assert provider.requests[0]["auth"] == "Bearer sk-upstream-secret"  # provider key stays server-side
    assert r.json()["choices"][0]["message"]["content"] == "Antwort an Max Mustermann: Ihr Anliegen wird bearbeitet."
    assert r.headers["X-OpenAnonymizer-Outcome"] == "allow"


def test_placeholders_consistent_across_messages(tmp_path):
    provider = FakeProvider()
    c = make_client(tmp_path, provider)
    chat(c, "Herr Max Mustermann hat angerufen.", "Bitte schreibe Herrn Max Mustermann und Frau Erika Beispiel.")
    msgs = provider.requests[0]["body"]["messages"]
    assert "PERSON_001" in msgs[1]["content"] and "PERSON_001" in msgs[2]["content"]
    assert "PERSON_002" in msgs[2]["content"]


def test_restore_can_be_disabled(tmp_path):
    provider = FakeProvider()
    c = make_client(tmp_path, provider, restore=False)
    r = chat(c, "Herr Max Mustermann hat angerufen.")
    assert "PERSON_001" in r.json()["choices"][0]["message"]["content"]


def test_local_only_content_is_refused_without_local_model(tmp_path):
    provider = FakeProvider()
    c = make_client(tmp_path, provider)
    r = chat(c, "Herr Max Mustermann leidet an einer Depression.")
    assert r.status_code == 403 and r.json()["error"]["type"] == "anonymizer_policy_violation"
    assert r.json()["error"]["code"] == "local_only" and provider.requests == []
    assert "Mustermann" not in r.text and "Depression" not in r.text


def test_local_only_content_is_routed_to_local_model(tmp_path):
    provider = FakeProvider(reply=lambda body: "lokal beantwortet")
    c = make_client(tmp_path, provider, local=True)
    r = chat(c, "Herr Max Mustermann leidet an einer Depression.")
    assert r.status_code == 200
    req = provider.requests[0]
    assert req["url"].startswith("http://ollama.local/v1") and req["body"]["model"] == "llama3.1"
    trace = c.get(f"/v1/traces/{r.headers['X-OpenAnonymizer-Trace-Id']}", headers=H).json()
    assert trace["destination"] == "local" and "routed to local model" in json.dumps(trace["steps"])


def test_non_text_content_and_streaming_rejected(tmp_path):
    c = make_client(tmp_path, FakeProvider())
    r = c.post("/v1/chat/completions", headers=H, json={"model": "m", "messages": [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:..."}}]}]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_content"
    r = chat(c, "Hallo", stream=True)
    assert r.status_code == 400 and r.json()["error"]["code"] == "stream_not_supported"


def test_tool_call_arguments_are_protected(tmp_path):
    provider = FakeProvider()
    c = make_client(tmp_path, provider)
    r = c.post("/v1/chat/completions", headers=H, json={"model": "gpt-4o", "messages": [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {
            "name": "send_mail", "arguments": json.dumps({"to": "max@example.org", "body": "Herr Max Mustermann"})}}]},
        {"role": "tool", "tool_call_id": "1", "content": "gesendet an max@example.org"},
    ]})
    assert r.status_code == 200
    sent = json.dumps(provider.requests[0]["body"])
    assert "max@example.org" not in sent and "Mustermann" not in sent


def test_upstream_error_and_unreachable(tmp_path):
    c = make_client(tmp_path, FakeProvider(status=500))
    r = chat(c, "Herr Max Mustermann hat angerufen.")
    assert r.status_code == 500 and r.json()["error"]["type"] == "upstream_error"

    def down(request):
        raise httpx.ConnectError("refused")
    env = {"ANONYMIZER_API_KEYS": KEY, "ANONYMIZER_POLICY_DIR": str(tmp_path / "q"), "ANONYMIZER_ACCOUNTS_DB": ":memory:", "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": ":memory:",
           "ANONYMIZER_UPSTREAM_URL": "https://api.provider.test/v1"}
    c2 = TestClient(create_app(Settings.from_env(env), gateway_transport=httpx.MockTransport(down)))
    assert chat(c2, "Hallo Welt, wie geht es?").status_code == 502


def test_no_upstream_configured(tmp_path):
    c = TestClient(create_app(Settings.from_env({"ANONYMIZER_API_KEYS": KEY, "ANONYMIZER_POLICY_DIR": str(tmp_path / "p"),
                                                 "ANONYMIZER_ACCOUNTS_DB": ":memory:", "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": ":memory:"})))
    assert chat(c, "Hallo").status_code == 503


def test_gateway_requires_anonymizer_key(tmp_path):
    c = make_client(tmp_path, FakeProvider())
    r = c.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 401


# --- traces & metrics -------------------------------------------------------------

def test_traces_and_metrics_contain_no_raw_values(tmp_path):
    provider = FakeProvider()
    c = make_client(tmp_path, provider)
    chat(c, "Unser Mandant Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00.")
    chat(c, "Herr Max Mustermann leidet an einer Depression.")
    c.post("/v1/protect", headers=H, json={"text": "Herr Max Mustermann bittet um Rückruf."})
    traces = c.get("/v1/traces", headers=H).json()
    assert len(traces) == 3
    assert {t["outcome"] for t in traces} == {"allow", "local_only"}
    gw = next(t for t in traces if t["route"] == "/v1/chat/completions" and t["outcome"] == "allow")
    assert gw["provider"] == "openai" and gw["model"] == "gpt-4o" and gw["entity_counts"]["iban"] == 1
    assert [s["name"] for s in gw["steps"]][-2:] == ["Provider request", "Response restore"]
    m = c.get("/v1/metrics", headers=H).json()
    assert m["requests"] == 3 and m["not_allowed"] == 1 and m["by_provider"]["openai"] == 2
    assert m["entity_distribution"]["person"] >= 3
    dump = json.dumps(traces) + json.dumps(m)
    for secret in ("Mustermann", "DE89", "Depression", "PERSON_001", "sk-upstream-secret"):
        assert secret not in dump
    assert c.get("/v1/traces/req_missing", headers=H).status_code == 404


def test_openai_sdk_compatibility(tmp_path):
    openai = pytest.importorskip("openai")
    provider = FakeProvider()
    app_client = make_client(tmp_path, provider)
    # TestClient is an httpx.Client, so the real OpenAI SDK talks to the in-process app.
    client = openai.OpenAI(api_key=KEY, base_url="http://testserver/v1", http_client=app_client)
    resp = client.chat.completions.create(model="gpt-4o", messages=[
        {"role": "user", "content": "Herr Max Mustermann hat angerufen."}])
    assert resp.choices[0].message.content.startswith("Antwort an Max Mustermann")
    assert "Mustermann" not in json.dumps(provider.requests[0]["body"])


def test_metrics_dashboard_fields():
    from anonymizer.tracing import Trace, TraceStore

    store = TraceStore()
    store.add(Trace(route="/mcp/proxy", upstream="crm", tool="get", outcome="allow", entity_counts={"person": 2},
                    fields={"$.name": {"person": 2}}, latency_ms=10, resource="c1"))
    store.add(Trace(route="/v1/protect", outcome="block", latency_ms=30, needs_review=True))
    store.add(Trace(route="/v1/protect", outcome="allow", status=502, warnings=["x"]))
    m = store.metrics(24)
    assert m["needs_review"] == 1 and m["with_warnings"] == 1 and m["resources_read"] == 1
    assert m["top_fields"] == {"$.name": 2}
    ops = {o["name"]: o for o in m["by_operation"]}
    assert ops["crm__get"]["entities"] == 2 and ops["/v1/protect"]["errors"] == 1
    last = m["timeseries"][-1]
    assert (last["anonymized"], last["not_allowed"], last["errors"], last["clean"]) == (1, 1, 1, 0)
    assert m["previous"]["requests"] == 0 and m["last_trace_at"] is not None
    assert m["latency_ms"]["p50"] == 10 and m["latency_ms"]["p95"] == 30
