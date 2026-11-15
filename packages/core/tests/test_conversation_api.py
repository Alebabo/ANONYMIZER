"""REST and MCP (stdio tools + streamable HTTP) for conversations and prompts."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from cato.api import create_app
from cato.api.settings import Settings
from cato.mcp import CatoTools, MCPConfig, ToolError, build_server, parse_time, tools_from_env

API_KEY = "cato_test_user_key_0123456789abcdef"
ADMIN_KEY = "cato_test_admin_key_0123456789abcdef"
USER = {"Authorization": f"Bearer {API_KEY}"}
ADMIN = {"X-API-Key": ADMIN_KEY}
SECRETS = ["Mustermann", "max.mustermann@example.org", "Diabetes", "sess-", "4711-2231"]
GOOD = "Du bist ein Support-Assistent. Sprich {{customer_name}} höflich an."


def conversation(i: int) -> dict:
    return {
        "id": f"sess-{i:03d}", "created_at": 1762905600 + i * 60, "language": "de", "tags": ["billing"],
        "prompt": "support-bot", "prompt_version": 1,
        "messages": [
            {"role": "user", "content": "Mein Name ist Max Mustermann, Bestellung 4711-2231, "
                                        "max.mustermann@example.org", "created_at": 1762905600 + i * 60},
            {"role": "assistant", "content": "Danke, ich prüfe die Bestellung 4711-2231."},
            {"role": "user", "content": "Ich habe Diabetes."},
        ],
    }


@pytest.fixture
def env(tmp_path):
    src = tmp_path / "c.jsonl"
    src.write_text("\n".join(json.dumps(conversation(i)) for i in range(12)) + "\n", encoding="utf-8")
    patterns = tmp_path / "patterns.yaml"
    patterns.write_text("patterns:\n  - name: order_number\n    pattern: '\\b\\d{4}-\\d{4}\\b'\n"
                        "    confidence: 0.9\n", encoding="utf-8")
    return {
        "CATO_API_KEYS": API_KEY, "CATO_ADMIN_KEYS": ADMIN_KEY,
        "CATO_POLICY_DIR": str(tmp_path / "policies"), "CATO_ACCOUNTS_DB": ":memory:",
        "CATO_AUDIT_DB": ":memory:", "CATO_TRACE_DB": ":memory:",
        "CATO_SOURCE": "jsonl", "CATO_SOURCE_PATH": str(src), "CATO_CUSTOM_PATTERNS": str(patterns),
        "CATO_CONVERSATIONS_DB": str(tmp_path / "conv.db"), "CATO_CONVERSATIONS_DAILY_LIMIT": "3",
        "CATO_CONVERSATIONS_MIN_GROUP": "5", "CATO_PROMPTS": "local", "CATO_PROMPTS_DB": str(tmp_path / "p.db"),
        "CATO_MCP_HTTP": "1",
    }


@pytest.fixture
def client(env):
    with TestClient(create_app(Settings.from_env(env))) as c:
        yield c


def clean(obj) -> bool:
    dump = json.dumps(obj, ensure_ascii=False)
    return not any(s in dump for s in SECRETS)


# --- REST ------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/v1/sources", "/v1/conversations", "/v1/conversations/stats",
                                  "/v1/conversations/quota", "/v1/prompts"])
def test_require_key(client, path):
    assert client.get(path).status_code == 401


def test_sources_describe_without_secrets(client):
    body = client.get("/v1/sources", headers=USER).json()
    assert body["conversations"]["kind"] == "jsonl" and body["conversation_policy"] == "support-default"
    assert body["prompts"] == {"backend": "local"} and body["mcp_http"]


def test_conversation_flow(client):
    page = client.get("/v1/conversations?limit=2", headers=USER).json()
    assert len(page["data"]) == 2 and clean(page)
    cid = page["data"][0]["id"]
    conv = client.get(f"/v1/conversations/{cid}", headers=USER)
    assert conv.status_code == 200 and clean(conv.json())
    msgs = conv.json()["messages"]
    assert "ORDER_NUMBER_001" in msgs[0]["content"] and "ORDER_NUMBER_001" in msgs[1]["content"]
    assert msgs[2]["content"] is None
    trace = client.get(f"/v1/traces/{conv.json()['trace_id']}", headers=USER).json()
    assert trace["route"] == "/v1/conversations" and clean(trace)
    audit = client.get("/v1/audit-logs?resource_type=conversation", headers=ADMIN).json()
    assert audit["data"][0]["resource_id"] == cid and clean(audit)
    assert client.get("/v1/conversations/quota", headers=USER).json()["used"] == 1
    stats = client.get("/v1/conversations/stats?group_by=prompt_version", headers=USER).json()
    assert stats["groups"] == [{"key": "support-bot@1", "conversations": 12, "messages": 36}]


def test_conversation_errors(client):
    assert client.get("/v1/conversations/sess-001", headers=USER).status_code == 400
    assert client.get("/v1/conversations/conv_0000000000000000", headers=USER).status_code == 404
    assert client.get("/v1/conversations?cursor=cur_0000000000000000", headers=USER).status_code == 400
    assert client.get("/v1/conversations/stats?group_by=email", headers=USER).status_code == 400
    ids = [h["id"] for h in client.get("/v1/conversations?limit=4", headers=USER).json()["data"]]
    for cid in ids[:3]:
        assert client.get(f"/v1/conversations/{cid}", headers=USER).status_code == 200
    r = client.get(f"/v1/conversations/{ids[3]}", headers=USER)
    assert r.status_code == 429 and "daily limit" in r.json()["detail"]


def test_prompt_flow(client):
    r = client.post("/v1/prompts", json={"name": "support-bot", "prompt": GOOD, "note": "init"}, headers=USER)
    assert r.status_code == 201 and r.json()["version"] == 1
    bad = client.post("/v1/prompts", json={"name": "support-bot", "prompt": "Wie bei Max Mustermann"}, headers=USER)
    assert bad.status_code == 422 and "Mustermann" not in bad.text
    chat = client.post("/v1/prompts", json={"name": "chat", "prompt": [{"role": "system", "content": GOOD}]},
                       headers=USER)
    assert chat.status_code == 201 and chat.json()["type"] == "chat"
    assert client.post("/v1/prompts/support-bot/labels", json={"version": 1, "label": "production"},
                       headers=USER).status_code == 403
    r = client.post("/v1/prompts/support-bot/labels", json={"version": 1, "label": "production"}, headers=ADMIN)
    assert r.json() == {"name": "support-bot", "label": "production", "version": 1, "previous_version": None}
    assert client.get("/v1/prompts/support-bot?label=production", headers=USER).json()["version"] == 1
    client.post("/v1/prompts", json={"name": "support-bot", "prompt": GOOD + " Kurz."}, headers=USER)
    assert len(client.get("/v1/prompts/support-bot/history", headers=USER).json()) == 2
    diff = client.get("/v1/prompts/support-bot/diff?from_version=1&to_version=2", headers=USER).json()
    assert "Kurz." in diff["diff"]
    assert [p["name"] for p in client.get("/v1/prompts", headers=USER).json()] == ["chat", "support-bot"]
    assert client.get("/v1/prompts/missing", headers=USER).status_code == 404
    actions = {e["action"] for e in client.get("/v1/audit-logs?resource_type=prompt", headers=ADMIN).json()["data"]}
    assert actions == {"create", "label"}


def test_features_off_without_config(tmp_path):
    settings = Settings.from_env({"CATO_API_KEYS": API_KEY, "CATO_POLICY_DIR": str(tmp_path / "p"),
                                  "CATO_ACCOUNTS_DB": ":memory:", "CATO_AUDIT_DB": ":memory:",
                                  "CATO_TRACE_DB": ":memory:"})
    c = TestClient(create_app(settings))
    assert c.get("/v1/conversations", headers=USER).status_code == 404
    assert c.get("/v1/prompts", headers=USER).status_code == 404
    assert c.post("/mcp", json={}, headers=USER).status_code in (404, 405)
    assert c.get("/v1/sources", headers=USER).json() == {"conversations": None, "conversation_policy": None,
                                                         "prompts": None, "mcp_http": False}


# --- MCP over HTTP -------------------------------------------------------------------

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "mcp-protocol-version": "2025-06-18"}


def rpc(client, method, params=None, headers=USER, id_=1):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
                       headers={**MCP_HEADERS, **headers})


def call(client, name, args, headers=USER):
    r = rpc(client, "tools/call", {"name": name, "arguments": args}, headers)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    return result, json.loads(result["content"][0]["text"]) if not result.get("isError") else None


def test_mcp_http_requires_key(client):
    init = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
    assert rpc(client, "initialize", init, headers={}).status_code == 401
    assert rpc(client, "initialize", init, headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = rpc(client, "initialize", init)
    assert r.status_code == 200 and "Cato" in r.json()["result"]["instructions"]


def test_mcp_http_tools_and_scoping(client):
    names = {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert {"list_conversations", "get_conversation", "conversation_stats", "list_prompts", "get_prompt",
            "prompt_history", "diff_prompt", "create_prompt_draft"} <= names
    assert not any("label" in n or "promote" in n or "restore" in n for n in names)

    _, page = call(client, "list_conversations", {"since": "2025-11-12", "limit": 2})
    assert len(page["data"]) == 2 and clean(page)
    _, conv = call(client, "get_conversation", {"conversation_id": page["data"][0]["id"]})
    assert clean(conv) and conv["quota"]["used"] == 1
    # quota and audit are bound to the key that called, here the admin key
    _, conv2 = call(client, "get_conversation", {"conversation_id": page["data"][0]["id"]}, ADMIN)
    assert conv2["quota"]["used"] == 1
    audit = client.get("/v1/audit-logs?resource_type=conversation", headers=ADMIN).json()["data"]
    assert {e["actor_label"] for e in audit} == {"environment API key", "environment admin key"}

    _, draft = call(client, "create_prompt_draft", {"name": "support-bot", "text": GOOD})
    assert draft["version"] == 1 and draft["draft"]
    result, _ = call(client, "create_prompt_draft", {"name": "support-bot", "text": "Wie Max Mustermann"})
    assert result["isError"] and "sensitive data" in result["content"][0]["text"]
    _, stats = call(client, "conversation_stats", {"group_by": "tag"})
    assert stats["groups"][0]["key"] == "billing"


def test_mcp_tool_annotations(client):
    tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert tools["create_prompt_draft"]["annotations"]["readOnlyHint"] is False
    assert tools["get_conversation"]["annotations"]["idempotentHint"] is False
    for name, t in tools.items():
        props = set(t["inputSchema"].get("properties", {}))
        assert not props & {"destination", "policy", "namespace", "ctx", "principal"}, name


# --- MCP stdio tools ---------------------------------------------------------------------

def test_stdio_tools_from_env(env, tmp_path):
    tools = tools_from_env({**env, "CATO_CONVERSATIONS_DB": str(tmp_path / "stdio.db")})
    page = tools.list_conversations(limit=1)
    conv = tools.get_conversation(page["data"][0]["id"])
    assert clean(conv) and "ORDER_NUMBER_001" in conv["messages"][0]["content"]
    tools.create_prompt_draft("bot", text=GOOD)
    assert tools.get_prompt("bot")["version"] == 1
    with pytest.raises(ToolError, match="either text"):
        tools.create_prompt_draft("bot")
    with pytest.raises(ToolError, match="sensitive"):
        tools.create_prompt_draft("bot", text="Grüße an Max Mustermann")
    names = {t.name for t in asyncio.run(build_server(tools).list_tools())}
    assert "get_conversation" in names and "create_prompt_draft" in names


def test_disabled_tools_explain_themselves():
    t = CatoTools(MCPConfig())
    with pytest.raises(ToolError, match="CATO_SOURCE"):
        t.list_conversations()
    with pytest.raises(ToolError, match="CATO_PROMPTS"):
        t.list_prompts()
    names = {x.name for x in asyncio.run(build_server(t).list_tools())}
    assert "list_conversations" not in names and "list_prompts" not in names


@pytest.mark.parametrize("value,expected", [
    ("2025-11-12", 1762905600.0), ("2025-11-12T01:00:00Z", 1762909200.0), ("1762905600", 1762905600.0),
    (None, None), ("", None),
])
def test_parse_time(value, expected):
    assert parse_time(value) == expected


def test_parse_time_rejects_garbage():
    with pytest.raises(ToolError):
        parse_time("last tuesday")


def test_unknown_conversation_policy_fails_at_start(env):
    with pytest.raises(Exception, match="no-such-policy"):
        create_app(Settings.from_env({**env, "CATO_CONVERSATIONS_POLICY": "no-such-policy"}))


def test_unexpected_tool_errors_do_not_reach_the_model(env, tmp_path):
    tools = tools_from_env({**env, "CATO_CONVERSATIONS_DB": str(tmp_path / "x.db")})

    def boom(*a, **k):
        raise ValueError("raw source row: Max Mustermann")
    tools.conversations.source.list = boom
    with pytest.raises(ToolError) as exc:
        tools.list_conversations()
    assert "Mustermann" not in str(exc.value) and "internal error" in str(exc.value)
