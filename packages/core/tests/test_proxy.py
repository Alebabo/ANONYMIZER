"""MCP proxy: result filtering, tool exposure, traces, stdio and HTTP end to end (synthetic data only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
import mcp_types as types
import pytest
from fastapi.testclient import TestClient

from cato.api import create_app
from cato.api.settings import Settings
from cato.pipeline import Pipeline
from cato.policy import builtin_policy
from cato.proxy import DEFAULT_FIELD_HINTS, WITHHELD, CatoProxy, ProxyConfig, ResultFilter
from cato.tracing import TraceStore
from cato.vault import InMemoryVault, VaultKey

DEMO = Path(__file__).resolve().parents[3] / "examples" / "proxy" / "demo_db_server.py"
SECRETS = ["Mustermann", "Musterfrau", "max.mustermann@example.org", "erika@example.com", "1234567",
           "98765432", "DE89", "0532 0130", "Depression", "Hauptstraße", "Beispiel"]
API_KEY = "cato_test_user_key_0123456789abcdef"
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
    assert not leaks(trace.model_dump_json())             # traces carry types and paths only


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
    p = tmp_path / "cato-proxy.yaml"
    p.write_text(json.dumps(cfg))  # JSON is valid YAML
    return p


# --- stdio end to end -----------------------------------------------------------------------

def run_stdio(config: Path, calls: list[tuple[str, dict]]):
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "cato.proxy.server", "--config",
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
    env = {"CATO_API_KEYS": API_KEY, "CATO_POLICY_DIR": str(tmp_path / "pol"), "CATO_ACCOUNTS_DB": ":memory:",
           "CATO_AUDIT_DB": ":memory:", "CATO_TRACE_DB": ":memory:", "CATO_PROXY_CONFIG": str(cfg)}
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
    proxy = CatoProxy(ProxyConfig.model_validate({"upstreams": {"db": {"url": "http://127.0.0.1:9/mcp"}}}))
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
    from cato.policy.store import builtin_policy as bp
    import yaml

    (tmp_path / "strict.yaml").write_text(yaml.safe_dump(bp("support-default").model_dump(mode="json")))
    p = tmp_path / "p.yaml"
    p.write_text("policy: ./strict.yaml\nupstreams:\n  db:\n    url: http://127.0.0.1:9/mcp\n")
    monkeypatch.chdir("/")
    assert CatoProxy(ProxyConfig.load(p, {})).pipelines["db"].policy.name == "support-default"


def test_known_values_thread_safety():
    import threading

    from cato.proxy.filter import KnownValues

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
    proxy = CatoProxy(ProxyConfig.model_validate({"upstreams": {"x": {"command": [sys.executable, str(server)],
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
