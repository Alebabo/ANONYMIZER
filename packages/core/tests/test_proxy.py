"""MCP proxy: result filtering, tool exposure, traces, stdio and HTTP end to end (synthetic data only)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import anyio
import mcp_types as types
import pytest
from fastapi.testclient import TestClient

from anonymizer.api import create_app
from anonymizer.api.settings import Settings
from anonymizer.pipeline import Pipeline
from anonymizer.policy import builtin_policy
from anonymizer.proxy import DEFAULT_FIELD_HINTS, WITHHELD, AnonymizerProxy, ProxyConfig, ResultFilter
from anonymizer.tracing import TraceStore
from anonymizer.vault import InMemoryVault, VaultKey

DEMO = Path(__file__).resolve().parents[3] / "examples" / "proxy" / "demo_db_server.py"
SECRETS = ["Mustermann", "Musterfrau", "max.mustermann@example.org", "erika@example.com", "1234567",
           "98765432", "DE89", "0532 0130", "Depression", "Hauptstraße", "Beispiel"]
API_KEY = "anonymizer_test_user_key_0123456789abcdef"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "mcp-protocol-version": "2025-06-18"}


def leaks(text: str) -> list[str]:
    return [s for s in SECRETS if s in text]


def text_result(*items) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=i if isinstance(i, str) else
                                                           json.dumps(i, ensure_ascii=False)) for i in items])


@pytest.fixture(scope="module")
def pipeline():
    return Pipeline(builtin_policy("support-default"), vault=InMemoryVault(VaultKey.generate()))


def make_filter(pipeline, observe=False, **kw):
    return ResultFilter(pipeline, "external", "proxy:test", observe=observe, hints=DEFAULT_FIELD_HINTS, **kw)


ROWS = [{"id": 1, "vorname": "Max", "nachname": "Mustermann", "email": "max.mustermann@example.org",
         "telefon": "+49 170 1234567", "iban": "DE89 3704 0044 0532 0130 00", "segment": "privat",
         "notiz": "Kundin ist wegen einer Depression krankgeschrieben."},
        {"id": 2, "vorname": "Erika", "nachname": "Musterfrau", "email": "erika@example.com",
         "telefon": "030 98765432", "iban": "DE02 1203 0000 0000 2020 51", "segment": "premium", "notiz": "ok"}]


# --- filter ---------------------------------------------------------------------------------

def test_json_rows_are_protected_field_by_field(pipeline):
    out, report = make_filter(pipeline).apply(text_result(ROWS))
    data = json.loads(out.content[0].text)
    assert not leaks(out.content[0].text)
    assert list(data[0]) == list(ROWS[0])                 # keys stay readable
    assert data[0]["segment"] == "privat" and data[0]["id"] == 1
    assert data[0]["notiz"] == WITHHELD                   # special category -> local_only for external
    assert data[0]["vorname"].startswith("PERSON_") and data[0]["email"].startswith("EMAIL_")
    assert report.withheld == 1 and report.hinted >= 1
    trace = report.trace()
    assert trace.fields["$[].email"] == {"email": 2} and "health_data" in trace.entity_counts
    stored = TraceStore().add(trace)                      # content traces are off by default
    assert not leaks(stored.model_dump_json())            # stored traces carry types and paths only


def test_same_value_same_placeholder_across_calls(pipeline):
    f = make_filter(pipeline)
    a = json.loads(f.apply(text_result({"email": "max.mustermann@example.org"}))[0].content[0].text)
    b = json.loads(make_filter(pipeline).apply(text_result({"mail": "max.mustermann@example.org"}))[0]
                   .content[0].text)
    assert a["email"] == b["mail"]


def test_known_values_are_found_in_free_text(pipeline):
    f = make_filter(pipeline)
    f.apply(text_result({"vorname": "Jonas", "nachname": "Beispiel"}))
    out, report = f.apply(text_result({"text": "Gruß, Jonas Beispiel"}))
    assert "Beispiel" not in out.content[0].text and report.learned + len(report.parts) > 0


def test_identifiers_and_keys_are_not_over_redacted(pipeline):
    out, _ = make_filter(pipeline).apply(text_result({"customers": ["id", "vorname", "telefon", "iban"],
                                                      "status": "open"}))
    assert json.loads(out.content[0].text) == {"customers": ["id", "vorname", "telefon", "iban"], "status": "open"}


def test_data_in_keys_is_protected(pipeline):
    out, _ = make_filter(pipeline).apply(text_result({"max.mustermann@example.org": {"orders": 3}}))
    assert not leaks(out.content[0].text) and "orders" in out.content[0].text


def test_plain_text_and_structured_content(pipeline):
    raw = types.CallToolResult(
        content=[types.TextContent(type="text", text="Kunde Max Mustermann, IBAN DE89 3704 0044 0532 0130 00")],
        structured_content={"result": "Kunde Max Mustermann, IBAN DE89 3704 0044 0532 0130 00"})
    out, report = make_filter(pipeline).apply(raw)
    assert not leaks(out.content[0].text) and not leaks(json.dumps(out.structured_content))
    assert sum(report.trace().entity_counts.values()) == 2  # structured copy not counted twice


def test_non_text_content_is_withheld(pipeline):
    raw = types.CallToolResult(content=[types.ImageContent(type="image", data="aGVsbG8=", mime_type="image/png")])
    out, report = make_filter(pipeline).apply(raw)
    assert out.content[0].type == "text" and "withheld" in out.content[0].text and report.non_text == 1


def test_numbers_under_hinted_keys(pipeline):
    out, _ = make_filter(pipeline).apply(text_result({"telefon": 491701234567, "count": 4}))
    data = json.loads(out.content[0].text)
    assert data["count"] == 4 and "1234567" not in str(data["telefon"])


def test_observe_mode_returns_original_but_reports(pipeline):
    raw = text_result(ROWS)
    out, report = make_filter(pipeline, observe=True).apply(raw)
    assert out is raw
    assert report.trace().entity_counts.get("email") == 2 and report.withheld == 1


def test_oversized_result_is_withheld(pipeline):
    out, _ = make_filter(pipeline, max_chars=10).apply(text_result("Max Mustermann ruft an"))
    assert "withheld" in out.content[0].text and not leaks(out.content[0].text)


# --- config ---------------------------------------------------------------------------------

def test_config_env_substitution_and_validation(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("upstreams:\n  db:\n    url: ${URL}\n    headers: {Authorization: 'Bearer ${TOKEN}'}\n")
    cfg = ProxyConfig.load(p, {"URL": "http://x/mcp", "TOKEN": "t"})
    assert cfg.upstreams["db"].headers["Authorization"] == "Bearer t"
    with pytest.raises(ValueError, match="TOKEN"):
        ProxyConfig.load(p, {"URL": "http://x/mcp"})
    p.write_text("upstreams:\n  Bad-Name:\n    url: http://x\n")
    with pytest.raises(ValueError):
        ProxyConfig.load(p, {})
    p.write_text("upstreams:\n  db:\n    url: http://x\n    command: [a]\n")
    with pytest.raises(ValueError, match="exactly one"):
        ProxyConfig.load(p, {})


def demo_config(tmp_path, **upstream) -> Path:
    cfg = {"policy": "support-default", "trace_db": str(tmp_path / "traces.db"), "audit_db": str(tmp_path / "a.db"),
           "upstreams": {"demo": {"command": [sys.executable, str(DEMO)], **upstream}}}
    p = tmp_path / "anonymizer-proxy.yaml"
    p.write_text(json.dumps(cfg))  # JSON is valid YAML
    return p


# --- stdio end to end -----------------------------------------------------------------------

def run_stdio(config: Path, calls: list[tuple[str, dict]]):
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "anonymizer.proxy.server", "--config",
                                                                     str(config)])
        async with Client(params, read_timeout_seconds=120) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            return names, [await c.call_tool(n, a) for n, a in calls]

    return anyio.run(go)


def test_stdio_end_to_end(tmp_path):
    cfg = demo_config(tmp_path)
    names, results = run_stdio(cfg, [("demo__get_customers", {}), ("demo__get_tickets", {}),
                                     ("demo__export_customer", {"customer_id": 1}),
                                     ("demo__delete_customer", {"customer_id": 1})])
    assert "demo__get_customers" in names and "demo__delete_customer" not in names  # write tool hidden
    for r in results[:3]:
        dump = json.dumps([b.model_dump() for b in r.content], ensure_ascii=False) + json.dumps(r.structured_content)
        assert not leaks(dump), leaks(dump)
    assert results[3].is_error
    traces = [t for t in TraceStore(tmp_path / "traces.db").list(10) if t.upstream == "demo"]
    assert {t.tool for t in traces} == {"get_customers", "get_tickets", "export_customer"}
    assert all(not leaks(t.model_dump_json()) for t in traces)


def test_stdio_observe_mode_passes_raw_data(tmp_path):
    cfg = demo_config(tmp_path, mode="observe")
    _, results = run_stdio(cfg, [("demo__get_customers", {})])
    assert "Mustermann" in results[0].content[0].text  # observe = no protection, by design
    t = TraceStore(tmp_path / "traces.db").list(1)[0]
    assert t.mode == "observe" and t.entity_counts.get("email") == 3


# --- HTTP inside the API --------------------------------------------------------------------

def rpc(client, method, params=None, headers=None):
    return client.post("/proxy/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                       headers={**MCP_HEADERS, **(headers if headers is not None else
                                                  {"Authorization": f"Bearer {API_KEY}"})})


def test_http_proxy_in_api(tmp_path):
    cfg = demo_config(tmp_path, tools={"allow": ["get_customers", "list_tables"]})
    env = {"ANONYMIZER_API_KEYS": API_KEY, "ANONYMIZER_POLICY_DIR": str(tmp_path / "pol"), "ANONYMIZER_ACCOUNTS_DB": ":memory:",
           "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": ":memory:", "ANONYMIZER_PROXY_CONFIG": str(cfg)}
    with TestClient(create_app(Settings.from_env(env))) as c:
        assert rpc(c, "tools/list", headers={}).status_code == 401
        names = {t["name"] for t in rpc(c, "tools/list").json()["result"]["tools"]}
        assert names == {"demo__get_customers", "demo__list_tables"}
        r = rpc(c, "tools/call", {"name": "demo__get_customers", "arguments": {}})
        assert r.status_code == 200 and not leaks(r.text) and "PERSON_" in r.text
        r = rpc(c, "tools/call", {"name": "demo__get_tickets", "arguments": {}})
        assert r.json()["result"]["isError"]  # not in the allow list
        auth = {"Authorization": f"Bearer {API_KEY}"}
        status = c.get("/v1/proxy", headers=auth).json()
        assert status["upstreams"][0]["connected"] and status["upstreams"][0]["tools_exposed"] == 2
        traces = c.get("/v1/traces?route=/mcp/proxy", headers=auth).json()
        assert traces and traces[0]["upstream"] == "demo" and traces[0]["fields"]
        audit = c.get("/v1/audit-logs?resource_type=mcp_tool", headers=auth)
        assert audit.status_code in (200, 403)


def test_proxy_unknown_upstream_tool():
    proxy = AnonymizerProxy(ProxyConfig.model_validate({"upstreams": {"db": {"url": "http://127.0.0.1:9/mcp"}}}))
    r = anyio.run(proxy.call_tool, "nope__x", {})
    assert r.is_error and "unknown" in r.content[0].text


# --- review findings ------------------------------------------------------------------------

def test_structured_only_data_is_reported(pipeline):
    raw = types.CallToolResult(content=[types.TextContent(type="text", text="Found 2 rows")],
                               structured_content={"rows": ROWS})
    out, report = make_filter(pipeline).apply(raw)
    assert not leaks(json.dumps(out.structured_content, ensure_ascii=False))
    trace = report.trace()
    assert trace.entity_counts.get("email") == 2 and trace.fields["$.rows[].email"] == {"email": 2}


def test_long_numbers_without_hint_are_checked(pipeline):
    out, report = make_filter(pipeline).apply(text_result({"card": 4111111111111111, "id": 1234567, "ts": 1731600000}))
    data = json.loads(out.content[0].text)
    assert "4111111111111111" not in out.content[0].text and data["id"] == 1234567 and data["ts"] == 1731600000
    assert report.trace().entity_counts == {"credit_card": 1}


def fresh_pipeline():
    return Pipeline(builtin_policy("support-default"), vault=InMemoryVault(VaultKey.generate()))


def test_ner_batch_only_for_free_text_and_output_unchanged(monkeypatch):
    rows = ROWS + [{"id": 3, "vorname": "Jan", "notiz": "Anruf von Erika Musterfrau aus Köln wegen der Karte."}]
    unbatched = fresh_pipeline()
    monkeypatch.setattr(unbatched.detector, "prefetch", lambda texts, lang: None)
    expected = make_filter(unbatched).apply(text_result(rows))[0].content[0].text

    batched, seen = fresh_pipeline(), []
    real = batched.detector.prefetch
    monkeypatch.setattr(batched.detector, "prefetch", lambda texts, lang: (seen.extend(texts), real(texts, lang)))
    assert make_filter(batched).apply(text_result(rows))[0].content[0].text == expected
    assert rows[2]["notiz"] in seen                                  # free text goes through the batch
    assert not {"Max", "Mustermann", "max.mustermann@example.org", "privat"} & set(seen)  # hinted / identifiers


def test_hinted_value_with_extra_letters_gets_the_full_detector(monkeypatch):
    p, calls = fresh_pipeline(), []
    real = p.detector.scan
    monkeypatch.setattr(p.detector, "scan", lambda text, lang=None: (calls.append(text), real(text, lang))[1])
    make_filter(p).apply(text_result([{"email": "max.mustermann@example.org"}, {"email": "max.mustermann@example.org Max"}]))
    assert calls == ["max.mustermann@example.org Max"]  # the clean value needs rules only


def test_oversized_structured_content_is_withheld(pipeline):
    raw = types.CallToolResult(content=[types.TextContent(type="text", text="ok")],
                               structured_content={"rows": ROWS})
    out, _ = make_filter(pipeline, max_chars=50).apply(raw)
    assert out.structured_content is None and "withheld" in out.content[0].text


def test_config_values_with_yaml_characters_and_comments(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("upstreams:\n  db:\n    command: [x]\n    env: {URI: '${URI}'}\n"
                 "    # headers: {Authorization: 'Bearer ${NOT_SET}'}\n")
    cfg = ProxyConfig.load(p, {"URI": "postgres://u:p #a: 'b'@h/db"})
    assert cfg.upstreams["db"].env["URI"] == "postgres://u:p #a: 'b'@h/db"
    p.write_text("upstreams:\n  my__db:\n    url: http://x\n")
    with pytest.raises(ValueError):
        ProxyConfig.load(p, {})


def test_relative_policy_file_resolves_against_config(tmp_path, monkeypatch):
    from anonymizer.policy.store import builtin_policy as bp
    import yaml

    (tmp_path / "strict.yaml").write_text(yaml.safe_dump(bp("support-default").model_dump(mode="json")))
    p = tmp_path / "p.yaml"
    p.write_text("policy: ./strict.yaml\nupstreams:\n  db:\n    url: http://127.0.0.1:9/mcp\n")
    monkeypatch.chdir("/")
    assert AnonymizerProxy(ProxyConfig.load(p, {})).pipelines["db"].policy.name == "support-default"


def test_known_values_thread_safety():
    import threading

    from anonymizer.proxy.filter import KnownValues

    known, errors = KnownValues(), []

    def work(n):
        try:
            for i in range(300):
                known.add(f"Name{n}x{i}", "person")
                known.find(f"Hallo Name{n}x{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(known.values) == 1200


def test_upstream_reconnects_after_exit(tmp_path):
    server = tmp_path / "once.py"
    server.write_text("import os\nfrom mcp.server.mcpserver import MCPServer\ns = MCPServer(name='x')\n"
                      "@s.tool()\ndef ping() -> str:\n    return 'pong'\n"
                      "@s.tool()\ndef die() -> str:\n    os._exit(1)\n"
                      "s.run('stdio')\n")
    proxy = AnonymizerProxy(ProxyConfig.model_validate({"upstreams": {"x": {"command": [sys.executable, str(server)],
                                                                      "timeout": 20}}}))

    async def go():
        async with anyio.create_task_group() as tg:
            tg.start_soon(proxy.run)
            await proxy.wait_ready()
            first = await proxy.call_tool("x__ping", {})
            dead = await proxy.call_tool("x__die", {})
            with anyio.fail_after(30):
                while True:
                    again = await proxy.call_tool("x__ping", {})
                    if not again.is_error:
                        break
                    await anyio.sleep(0.5)
            proxy.stop()
            tg.cancel_scope.cancel()
        return first, dead, again

    first, dead, again = anyio.run(go)
    assert "pong" in first.content[0].text and dead.is_error and "pong" in again.content[0].text


# --- data volume, log mode, OAuth -----------------------------------------------------------

def test_traces_record_argument_and_result_size(tmp_path):
    cfg = demo_config(tmp_path)
    _, results = run_stdio(cfg, [("demo__get_customers", {})])
    t = TraceStore(tmp_path / "traces.db").list(1)[0]
    sent = "\n".join(b.text for b in results[0].content if isinstance(b, types.TextContent))
    assert t.args_chars == 2 and t.result_chars == len(sent) > 0
    assert not t.content  # content only with content traces


def test_stdio_log_mode_passes_raw_data_without_detection(tmp_path):
    cfg = demo_config(tmp_path, mode="log")
    _, results = run_stdio(cfg, [("demo__get_customers", {})])
    assert "Mustermann" in results[0].content[0].text
    t = TraceStore(tmp_path / "traces.db").list(1)[0]
    assert t.mode == "log" and not t.entity_counts and t.result_chars and t.result_chars > 100


def test_oauth_config_needs_http_upstream():
    with pytest.raises(ValueError):
        ProxyConfig.model_validate({"upstreams": {"x": {"command": ["x"], "oauth": True}}})
    cfg = ProxyConfig.model_validate({"upstreams": {"a": {"url": "http://127.0.0.1:9/mcp"},
                                                    "b": {"url": "http://127.0.0.1:9/mcp", "oauth": True}}})
    proxy = AnonymizerProxy(cfg)
    assert proxy.upstreams["a"].auth is None and proxy.upstreams["b"].auth is not None


def test_oauth_token_storage_and_callback(tmp_path):
    import threading
    import urllib.request

    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

    from anonymizer.proxy.oauth import FileTokenStorage, _CallbackServer

    store = FileTokenStorage(tmp_path / "a.json", "http://127.0.0.1:1/callback")
    assert anyio.run(store.get_tokens) is None
    anyio.run(store.set_tokens, OAuthToken(access_token="at", refresh_token="rt"))
    anyio.run(store.set_client_info, OAuthClientInformationFull(client_id="c",
                                                                redirect_uris=["http://127.0.0.1:1/callback"]))
    assert anyio.run(store.get_tokens).refresh_token == "rt"
    assert anyio.run(store.get_client_info).client_id == "c"
    other = FileTokenStorage(tmp_path / "a.json", "http://127.0.0.1:2/callback")
    assert anyio.run(other.get_client_info) is None  # other callback port: register again

    server = _CallbackServer(0)
    port = server.server.server_address[1]
    threading.Thread(target=lambda: urllib.request.urlopen(
        f"http://127.0.0.1:{port}/callback?code=abc&state=s1", timeout=5).read()).start()
    got = server.wait(5)
    assert got.code == "abc" and got.state == "s1"


# --- on/off switch per upstream ---------------------------------------------------------------

def test_http_toggle_upstream_persists_and_hides_tools(tmp_path):
    cfg = demo_config(tmp_path)
    env = {"ANONYMIZER_API_KEYS": API_KEY, "ANONYMIZER_ADMIN_KEYS": "anonymizer_admin_key_0123456789abcdef",
           "ANONYMIZER_POLICY_DIR": str(tmp_path / "pol"), "ANONYMIZER_ACCOUNTS_DB": ":memory:",
           "ANONYMIZER_AUDIT_DB": ":memory:", "ANONYMIZER_TRACE_DB": ":memory:", "ANONYMIZER_PROXY_CONFIG": str(cfg)}
    admin = {"Authorization": "Bearer anonymizer_admin_key_0123456789abcdef"}
    with TestClient(create_app(Settings.from_env(env))) as c:
        assert any(t["name"].startswith("demo__") for t in rpc(c, "tools/list").json()["result"]["tools"])
        assert c.put("/v1/proxy/upstreams/demo", json={"enabled": False}, headers={"Authorization": f"Bearer {API_KEY}"}
                     ).status_code == 403  # admin only
        assert c.put("/v1/proxy/upstreams/nope", json={"enabled": False}, headers=admin).status_code == 404
        assert c.put("/v1/proxy/upstreams/demo", json={"enabled": False}, headers=admin).json()["enabled"] is False
        assert rpc(c, "tools/list").json()["result"]["tools"] == []
        up = c.get("/v1/proxy", headers=admin).json()["upstreams"][0]
        assert up["enabled"] is False and up["connected"] is False
        assert c.put("/v1/proxy/upstreams/demo", json={"enabled": True}, headers=admin).json()["enabled"] is True
        for _ in range(100):  # reconnect runs in the background
            if c.get("/v1/proxy", headers=admin).json()["upstreams"][0]["connected"]:
                break
            time.sleep(0.2)
        r = rpc(c, "tools/call", {"name": "demo__get_customers", "arguments": {}})
        assert not r.json()["result"].get("isError")
        assert c.put("/v1/proxy/upstreams/demo", json={"enabled": False}, headers=admin).status_code == 200
    assert ProxyConfig.load(cfg).upstreams["demo"].enabled is False  # saved next to the YAML, survives a restart
