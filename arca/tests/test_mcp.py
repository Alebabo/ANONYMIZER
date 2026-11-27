"""Der MCP-Server kann vault.db nicht öffnen und nur lesend auf visible.db zugreifen."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from arca import vault_db
from arca.release import release

SERVER = Path(__file__).resolve().parents[1] / "mcp" / "server.py"
spec = importlib.util.spec_from_file_location("arca_mcp_server", SERVER)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)


@pytest.fixture()
def released_db(paths, vault, arca):
    release(vault, paths[1], arca.preview(list(vault_db.COLUMNS))["id"])
    return srv.VisibleDB(paths[1])


# --- statisch: kein Wissen über vault.db ------------------------------------------------------

def _code_strings(tree: ast.AST) -> list[str]:
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def test_server_imports_nothing_from_arca_or_env():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules <= {"__future__", "argparse", "json", "sqlite3", "pathlib", "mcp"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"environ", "getenv", "os"}
    for s in _code_strings(tree):
        assert "vault" not in s.lower() and "ARCA_" not in s


# --- Laufzeit ------------------------------------------------------------------------------------

def test_refuses_vault_path(paths, vault):
    with pytest.raises(srv.QueryError):
        srv.VisibleDB(paths[0])


def test_attach_vault_denied(paths, released_db):
    vault_path = str(paths[0])
    with pytest.raises(srv.QueryError):
        released_db._run(f"ATTACH DATABASE '{vault_path}' AS v")
    assert "error" not in released_db.query("SELECT COUNT(*) FROM mandate")
    with pytest.raises(srv.QueryError):
        released_db.query("SELECT * FROM pragma_database_list")


def test_multiple_statements_rejected(paths, released_db):
    """Ein ATTACH lässt sich nicht hinter ein SELECT hängen."""
    with pytest.raises(srv.QueryError):
        released_db.query(f"SELECT * FROM mandate; ATTACH '{paths[0]}' AS v")


@pytest.mark.parametrize("sql", [
    "DELETE FROM mandate", "INSERT INTO mandate (zeile) VALUES (99)", "DROP TABLE mandate",
    "PRAGMA table_info(mandate)", "CREATE TABLE x (a)", "UPDATE mandate SET zeile = 1",
])
def test_only_select(released_db, sql):
    with pytest.raises(srv.QueryError):
        released_db.query(sql)
    with pytest.raises(srv.QueryError):
        released_db._run(sql)


def test_read_only_connection(paths, released_db):
    conn = released_db._connect()
    conn.set_authorizer(None)  # selbst ohne Authorizer: Datei ist read-only geöffnet
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM mandate")
    conn.close()


def test_tools_on_released_data(released_db):
    assert released_db.list_tables() == ["mandate"]
    info = released_db.describe_table("mandate")
    assert info["columns"][0] == "zeile" and info["rows"] == len(vault_db.SEED)
    result = released_db.query("SELECT mandant FROM mandate ORDER BY zeile")
    assert all(r[0].startswith("PERSON_") for r in result["rows"])


def test_empty_before_release(paths):
    assert srv.VisibleDB(paths[1]).list_tables() == []


@pytest.mark.skipif(shutil.which(sys.executable) is None, reason="kein Python")
def test_stdio_end_to_end(paths, released_db):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-I", str(SERVER), "--db", str(paths[1])], env={})

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = sorted(t.name for t in (await session.list_tools()).tools)
                res = await session.call_tool("query", {"sql": "SELECT mandant, sachverhalt FROM mandate"})
                bad = await session.call_tool("query", {"sql": f"ATTACH '{paths[0]}' AS v"})
                return tools, res, bad

    tools, res, bad = asyncio.run(run())
    assert tools == ["describe_table", "list_tables", "query"]
    text = res.content[0].text
    assert "Mustermann" not in text and "PERSON_" in text
    assert "error" in json.loads(bad.content[0].text)
