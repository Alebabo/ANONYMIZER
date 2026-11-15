import json

import httpx
import pytest

from cato.sources import HttpSource, JsonlSource, LangfuseSource, SourceError, source_from_env

CONV = {
    "id": "sess-1", "created_at": 1762905600, "language": "de", "tags": ["billing"], "prompt": "bot",
    "prompt_version": 3,
    "messages": [{"role": "user", "content": "Ich bin Max Mustermann", "created_at": 1762905600},
                 {"role": "assistant", "content": "Hallo!", "created_at": 1762905660}],
}


@pytest.fixture
def jsonl(tmp_path):
    p = tmp_path / "c.jsonl"
    rows = [CONV, {**CONV, "id": "sess-2", "created_at": 1762992000, "tags": ["delivery"]}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_jsonl_list_filters_and_pages(jsonl):
    s = JsonlSource(jsonl)
    page = s.list(limit=1)
    assert [h.id for h in page.data] == ["sess-2"] and page.next_cursor == "1"
    assert [h.id for h in s.list(cursor="1").data] == ["sess-1"]
    assert [h.id for h in s.list(tag="billing").data] == ["sess-1"]
    assert [h.id for h in s.list(since=1762950000).data] == ["sess-2"]
    assert s.list().data[0].message_count == 2
    assert s.get("sess-1").messages[0].content == "Ich bin Max Mustermann"


def test_jsonl_errors_never_echo_content(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"id": "x", "secret": "Max Mustermann"\n', encoding="utf-8")
    with pytest.raises(SourceError) as exc:
        JsonlSource(p).list()
    assert "Mustermann" not in str(exc.value) and "line 1" in str(exc.value)
    with pytest.raises(SourceError, match="not point to a file"):
        JsonlSource(tmp_path / "missing.jsonl")


def http_transport(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/conversations":
            return httpx.Response(200, json={"data": [{k: v for k, v in CONV.items() if k != "messages"}],
                                             "next_cursor": "after-sess-1"})
        if request.url.path == "/api/conversations/sess-1":
            return httpx.Response(200, json=CONV)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_http_contract():
    seen: list = []
    s = HttpSource("https://chat.internal/api/", "srckey", transport=http_transport(seen))
    page = s.list(since=1.0, limit=5)
    assert page.data[0].id == "sess-1" and page.next_cursor == "after-sess-1"
    assert seen[0].headers["authorization"] == "Bearer srckey"
    assert seen[0].url.params["since"] == "1.0" and "until" not in seen[0].url.params
    assert s.get("sess-1").messages[1].role == "assistant"
    with pytest.raises(SourceError, match="not found"):
        s.get("nope")
    assert s.describe() == {"kind": "http", "location": "https://chat.internal"}
    s.list(cursor="a/b")  # cursors and ids are passed encoded, never as path segments
    with pytest.raises(SourceError, match="not found"):
        s.get("../admin")
    assert seen[-1].url.raw_path == b"/api/conversations/..%2Fadmin"
    assert all(r.url.path.startswith("/api/") for r in seen)


def test_http_contract_violation_and_outage():
    bad = HttpSource("https://x", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"rows": 1})))
    with pytest.raises(SourceError, match="contract"):
        bad.list()

    def boom(request):
        raise httpx.ConnectError("down")
    with pytest.raises(SourceError, match="unreachable"):
        HttpSource("https://x", transport=httpx.MockTransport(boom)).list()


LF_SESSION = {
    "id": "lf-sess", "createdAt": "2026-11-10T09:00:00.000Z",
    "traces": [
        {"id": "t2", "timestamp": "2026-11-10T09:02:00Z",
         "input": {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "first"},
                                {"role": "assistant", "content": "a1"}, {"role": "user", "content": "second"}]},
         "output": {"role": "assistant", "content": "answer two"},
         "metadata": {"prompt_name": "support-bot", "prompt_version": 12}, "tags": ["web"]},
        {"id": "t1", "timestamp": "2026-11-10T09:00:00Z", "input": "first", "output": "answer one"},
    ],
}


def test_langfuse_sessions_become_conversations():
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/public/sessions":
            return httpx.Response(200, json={"data": [{"id": "lf-sess", "createdAt": "2026-11-10T09:00:00Z"}],
                                             "meta": {"page": 1, "totalPages": 2}})
        if request.url.path == "/api/public/sessions/lf-sess":
            return httpx.Response(200, json=LF_SESSION)
        return httpx.Response(404)

    s = LangfuseSource("https://cloud.langfuse.com", "pk", "sk", transport=httpx.MockTransport(handler))
    page = s.list(since=1762905600)
    assert page.data[0].id == "lf-sess" and page.next_cursor == "2"
    assert seen[0].headers["authorization"].startswith("Basic ")
    assert seen[0].url.params["fromTimestamp"].endswith("Z")
    conv = s.get("lf-sess")
    assert [(m.role, m.content) for m in conv.messages] == [
        ("user", "first"), ("assistant", "answer one"), ("user", "second"), ("assistant", "answer two")]
    assert conv.prompt == "support-bot" and conv.prompt_version == 12 and conv.tags == ["web"]


def test_factory(jsonl):
    assert source_from_env({}) is None
    assert source_from_env({"CATO_SOURCE": "jsonl", "CATO_SOURCE_PATH": str(jsonl)}).kind == "jsonl"
    with pytest.raises(SourceError, match="unknown"):
        source_from_env({"CATO_SOURCE": "mysql"})
    with pytest.raises(SourceError, match="CATO_SOURCE_URL"):
        source_from_env({"CATO_SOURCE": "http"})
    with pytest.raises(SourceError, match="langfuse"):
        source_from_env({"CATO_SOURCE": "langfuse", "CATO_SOURCE_URL": "https://x"})
