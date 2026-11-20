from fastapi.testclient import TestClient

from anonymizer.api.app import create_app
from anonymizer.api.settings import Settings
from anonymizer.mcp import AnonymizerTools
from anonymizer.playground import PlaygroundError, parse_csv

KEY = "test_key_0123456789abcdef0123456789"
CSV = "vorname;nachname;email;notiz\nMax;Mustermann;max@example.org;Mustermann ruft morgen an\nErika;Musterfrau;erika@example.org;Kein Rückruf\n"


def _app(tmp_path, content=True):
    env = {"ANONYMIZER_API_KEYS": KEY, "ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL": "a@example.org",
           "ANONYMIZER_BOOTSTRAP_ADMIN_PASSWORD": "secret-password-1", "ANONYMIZER_ENABLE_NER": "0",
           "ANONYMIZER_TRACE_CONTENT": "1" if content else "0"}
    for k in ("TRACE", "ACCOUNTS", "AUDIT", "CONVERSATIONS", "PLAYGROUND"):
        env[f"ANONYMIZER_{k}_DB"] = str(tmp_path / f"{k.lower()}.db")
    env["ANONYMIZER_POLICY_DIR"] = str(tmp_path / "policies")
    app = create_app(Settings.from_env(env))
    c = TestClient(app)
    tok = c.post("/v1/auth/login", json={"email": "a@example.org", "password": "secret-password-1"}).json()["token"]
    return app, c, {"Authorization": f"Bearer {tok}"}


def test_parse_csv_detects_delimiter_and_bom():
    cols, rows = parse_csv("﻿a,b\n1,2\n\n3\n".encode())
    assert cols == ["a", "b"] and rows == [{"a": "1", "b": "2"}, {"a": "3", "b": ""}]
    try:
        parse_csv("a;b\n")
        raise AssertionError("expected error")
    except PlaygroundError:
        pass


def test_upload_query_compare_and_trace(tmp_path):
    _, c, s = _app(tmp_path)
    ds = c.post("/v1/playground/datasets", headers=s, json={"name": "kunden.csv", "csv": CSV}).json()
    assert ds["rows"] == 2 and ds["columns"] == ["vorname", "nachname", "email", "notiz"]
    # API keys may not upload
    assert c.post("/v1/playground/datasets", headers={"Authorization": f"Bearer {KEY}"},
                  json={"name": "x", "csv": CSV}).status_code in (401, 403)

    r = c.post(f"/v1/playground/datasets/{ds['id']}/query", headers=s, json={"query": "max"}).json()
    assert r["matched"] == 1 and r["original"][0]["vorname"] == "Max"
    sent = r["rows"][0]
    assert "Max" not in str(sent) and "Mustermann" not in str(sent) and "max@example.org" not in str(sent)
    assert sent["vorname"] != "Max" and "Mustermann" not in sent["notiz"]  # learned from the nachname column
    assert any(x["original"] == "max@example.org" for x in r["replacements"])

    t = c.get(f"/v1/traces/{r['trace_id']}", headers=s).json()
    assert t["route"] == "/v1/playground" and t["resource"] == ds["id"]
    assert any(ci["input"] == "max@example.org" for ci in t["content"])

    # API key: protected rows only, no originals
    k = c.post(f"/v1/playground/datasets/{ds['id']}/query", headers={"Authorization": f"Bearer {KEY}"}, json={}).json()
    assert "original" not in k and "replacements" not in k and len(k["rows"]) == 2
    assert "Erika" not in str(k["rows"])

    assert c.delete(f"/v1/playground/datasets/{ds['id']}", headers=s).status_code == 204
    assert c.get("/v1/playground/datasets", headers=s).json() == []


def test_mcp_tools_return_protected_rows_only():
    from anonymizer.detect import Detector, DetectorConfig
    from anonymizer.pipeline import Pipeline
    from anonymizer.playground import PlaygroundService, PlaygroundStore
    from anonymizer.policy import builtin_policy
    from anonymizer.tracing import TraceStore

    det = Detector(DetectorConfig(enable_ner=False))
    traces = TraceStore()
    svc = PlaygroundService(PlaygroundStore(), lambda v: Pipeline(builtin_policy("support-default"), detector=det, vault=v),
                            "support-default", traces=traces)
    tools = AnonymizerTools(detector=det, playground=svc)
    from anonymizer.conversations import LOCAL_PRINCIPAL
    ds = svc.upload(LOCAL_PRINCIPAL, "k.csv", CSV)
    assert tools.list_datasets()["datasets"][0]["id"] == ds["id"]
    r = tools.query_dataset(ds["id"], query="erika")
    assert r["matched"] == 1 and "original" not in r and "erika@example.org" not in str(r["rows"])
    t = traces.list(limit=1)[0] if hasattr(traces, "list") else None
    assert t is None or t.tool == "query_dataset"
    try:
        tools.query_dataset("ds_missing")
        raise AssertionError("expected ToolError")
    except Exception as exc:
        assert "not found" in str(exc)
    assert "not available" in _err(lambda: AnonymizerTools(detector=det).list_datasets())


def _err(fn):
    try:
        fn()
    except Exception as exc:
        return str(exc)
    return ""


def test_store_search_counts_and_pages_in_sqlite(tmp_path):
    from anonymizer.playground import PlaygroundStore
    store = PlaygroundStore(tmp_path / "p.db")
    rows = [{"Session ID": f"s{i // 3}", "Nachricht": "Hallo Ärger" if i % 2 else "Konto"} for i in range(30)]
    ds = store.add("org", "export.csv", ["Session ID", "Nachricht"], rows, "me")
    assert store.search(ds["id"], "", None, 0, 5)[0] == 30
    total, page = store.search(ds["id"], "ärger", None, 2, 3)
    assert total == 15 and [r["Nachricht"] for r in page] == ["Hallo Ärger"] * 3
    total, page = store.search(ds["id"], "s1", ["Session ID"], 0, 100)  # s1, s10..s19 minus missing
    assert total == sum(1 for r in rows if "s1" in r["Session ID"]) and all("s1" in r["Session ID"] for r in page)
    assert store.search(ds["id"], "hallo", ["Session ID"], 0, 10) == (0, [])


def test_hidden_columns_are_never_searched_shown_or_sent(tmp_path):
    _, c, s = _app(tmp_path)
    key = {"Authorization": f"Bearer {KEY}"}
    ds = c.post("/v1/playground/datasets", headers=s, json={"name": "kunden.csv", "csv": CSV}).json()
    url = f"/v1/playground/datasets/{ds['id']}"
    r = c.put(f"{url}/columns", headers=s, json={"hidden": ["notiz", "email"]})
    assert r.status_code == 200 and r.json()["hidden"] == ["email", "notiz"]  # upload order

    dash = c.post(f"{url}/query", headers=s, json={}).json()
    assert dash["columns"] == ["vorname", "nachname"]
    assert "notiz" not in dash["original"][0] and "max@example.org" not in str(dash)
    # Search does not look into hidden columns either (would reveal what they contain).
    assert c.post(f"{url}/query", headers=s, json={"query": "rückruf"}).json()["matched"] == 0
    # Asking for a hidden column explicitly does not bring it back.
    assert c.post(f"{url}/query", headers=key, json={"columns": ["email"]}).json()["columns"] == ["vorname", "nachname"]

    listed = c.get("/v1/playground/datasets", headers=key).json()[0]
    assert listed["columns"] == ["vorname", "nachname"] and "hidden" not in listed and "all_columns" not in listed
    mine = c.get("/v1/playground/datasets", headers=s).json()[0]
    assert mine["hidden"] == ["email", "notiz"] and mine["all_columns"] == ds["columns"]

    # Show again, and the guard rails
    assert c.put(f"{url}/columns", headers=s, json={"hidden": []}).json()["columns"] == ds["columns"]
    assert c.put(f"{url}/columns", headers=s, json={"hidden": ds["columns"]}).status_code == 400
    assert c.put(f"{url}/columns", headers=s, json={"hidden": ["nope"]}).status_code == 400
    assert c.put(f"{url}/columns", headers=key, json={"hidden": ["email"]}).status_code in (401, 403)
    entries = c.get("/v1/audit-logs?resource_type=playground_dataset&action=update", headers=s).json()["data"]
    assert len(entries) == 2  # hide and show again; refused calls write nothing
