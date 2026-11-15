import asyncio
import json
import os
import shutil
import sys

import pytest

from cato.mcp import CatoTools, MCPConfig, ToolError, build_server
from cato.vault import VaultKey

CLIENT_LETTER = "Unser Mandant Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00, bittet um Rückruf."
HEALTH_LETTER = "Herr Max Mustermann leidet an einer Depression."
SECRETS = ["Mustermann", "DE89 3704", "Depression"]


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "brief.txt").write_text(CLIENT_LETTER, encoding="utf-8")
    (root / "gesundheit.md").write_text(HEALTH_LETTER, encoding="utf-8")
    (root / "binary.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "outside.txt").write_text("Herr Geheim Außerhalb", encoding="utf-8")
    os.symlink(tmp_path / "outside.txt", root / "escape.txt")
    return root


@pytest.fixture
def tools(docs):
    return CatoTools(MCPConfig(root=docs.resolve()))


def no_secrets(obj):
    dump = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return not any(s in dump for s in SECRETS)


# --- tool behaviour -------------------------------------------------------------

def test_scan_classify_report_return_no_raw_values(tools):
    scan = tools.scan_document(CLIENT_LETTER, "de")
    assert {"person", "iban"} <= set(scan["entity_counts"])
    assert no_secrets(scan)
    assert no_secrets(tools.classify_content(CLIENT_LETTER, "de"))
    report = tools.get_privacy_report(CLIENT_LETTER, "de")
    assert report.startswith("# Cato privacy report") and "| person |" in report and no_secrets(report)


def test_anonymize_returns_safe_text_when_allowed(tools):
    r = tools.anonymize_content(CLIENT_LETTER, "de")
    assert r["allowed"] and "PERSON_001" in r["text"] and no_secrets(r)
    assert "untrusted data" in r["notice"]


def test_anonymize_refuses_when_policy_forbids(tools):
    r = tools.anonymize_content(HEALTH_LETTER, "de")
    assert not r["allowed"] and r["text"] is None and r["outcome"] == "local_only"
    assert no_secrets(r)


def test_check_policy_returns_no_text(tools):
    r = tools.check_privacy_policy(HEALTH_LETTER, "de")
    assert r["outcome"] == "local_only" and not r["may_send"] and "text" not in r


def test_read_document_protected(tools):
    r = tools.read_document_protected("brief.txt")
    assert r["allowed"] and r["file"] == "brief.txt" and "PERSON_001" in r["text"] and no_secrets(r)
    blocked = tools.read_document_protected("gesundheit.md")
    assert blocked["text"] is None and no_secrets(blocked)


def test_list_documents_excludes_unsupported_and_escaping_files(tools):
    files = tools.list_documents()["files"]
    assert files == ["brief.txt", "gesundheit.md"]


@pytest.mark.parametrize("path,msg", [
    ("../outside.txt", "outside"),
    ("/etc/passwd", "outside"),
    ("escape.txt", "outside"),          # symlink pointing outside the root
    ("binary.pdf", "unsupported"),
    ("missing.txt", "not found"),
    ("brief.txt\x00.md", "invalid"),
])
def test_file_access_guards(tools, path, msg):
    with pytest.raises(ToolError, match=msg):
        tools.read_document_protected(path)


def test_file_tools_disabled_without_root():
    t = CatoTools(MCPConfig())
    with pytest.raises(ToolError, match="disabled"):
        t.read_document_protected("brief.txt")


def test_size_limit(docs):
    t = CatoTools(MCPConfig(root=docs.resolve(), max_chars=10))
    with pytest.raises(ToolError, match="exceeds"):
        t.anonymize_content(CLIENT_LETTER)


def test_local_destination_set_by_operator(docs):
    t = CatoTools(MCPConfig(root=docs.resolve(), destination="local"))
    assert t.anonymize_content(HEALTH_LETTER, "de")["allowed"]


def test_consistent_pseudonyms_with_vault(tmp_path):
    cfg = MCPConfig(vault_key=VaultKey.generate().to_b64(), vault_path=tmp_path / "v.json", namespace="matter-1")
    t = CatoTools(cfg)
    a = t.anonymize_content("Herr Max Mustermann klagt.", "de")["text"]
    b = t.anonymize_content("Herr Erika Beispiel und Herr Max Mustermann.", "de")["text"]
    assert "PERSON_001" in a and "PERSON_001" in b and "PERSON_002" in b


@pytest.mark.parametrize("env", [
    {"CATO_MCP_DESTINATION": "cloud"},
    {"CATO_MCP_NAMESPACE": "m"},  # namespace without vault key
])
def test_config_validation(env):
    with pytest.raises(ToolError):
        MCPConfig.from_env(env)


# --- server surface -----------------------------------------------------------------

def test_server_surface_cannot_weaken_policy(tools):
    server = build_server(tools)
    listed = asyncio.run(server.list_tools())
    names = {t.name for t in listed}
    assert names == {"scan_document", "classify_content", "anonymize_content", "check_privacy_policy",
                     "get_privacy_report", "list_documents", "read_document_protected"}
    assert not any("restore" in n for n in names)
    for tool in listed:
        props = set(tool.input_schema.get("properties", {}))
        assert not props & {"destination", "policy", "namespace", "dry_run"}, tool.name
        assert tool.annotations.read_only_hint and not tool.annotations.open_world_hint


def test_server_without_root_hides_file_tools():
    names = {t.name for t in asyncio.run(build_server(CatoTools(MCPConfig())).list_tools())}
    assert "read_document_protected" not in names and "list_documents" not in names


def test_tool_error_reaches_client_cleanly(tools):
    server = build_server(tools)
    with pytest.raises(Exception, match="outside the allowed directory"):
        asyncio.run(server.call_tool("read_document_protected", {"path": "../outside.txt"}))


# --- end to end over stdio -------------------------------------------------------------

@pytest.mark.skipif(shutil.which("cato-mcp") is None, reason="cato-mcp entry point not installed")
def test_stdio_end_to_end(docs):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=shutil.which("cato-mcp"), args=[],
                                   env={**os.environ, "CATO_MCP_ROOT": str(docs)})

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                result = await session.call_tool("read_document_protected", {"path": "brief.txt"})
                return {t.name for t in listed.tools}, result

    names, result = asyncio.run(run())
    assert "read_document_protected" in names
    payload = json.loads(result.content[0].text)
    assert payload["allowed"] and "PERSON_001" in payload["text"] and no_secrets(payload)
