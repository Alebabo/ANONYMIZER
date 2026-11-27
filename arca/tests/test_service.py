"""HTTP-Ablauf: Vorschau -> Freigabe -> visible.db; ohne Freigabe gesperrt."""

from __future__ import annotations

from fastapi.testclient import TestClient

from arca.anonymize import ArcaAnonymizer
from arca.config import Config
from arca.service import create_app

from conftest import SECRET


def client(tmp_path, detector) -> TestClient:
    cfg = Config(data_dir=tmp_path, secret=SECRET)
    return TestClient(create_app(cfg))


def test_flow(tmp_path, detector, monkeypatch):
    monkeypatch.setattr("arca.service.ArcaAnonymizer", lambda conn, secret: ArcaAnonymizer(conn, secret, detector))
    c = client(tmp_path, detector)
    assert c.get("/status").json()["released"] is False
    t = c.get("/tables").json()
    assert t["visible"] == {"columns": [], "rows": []} and len(t["vault"]) == 5

    p = c.post("/preview", json={"columns": ["mandant", "sachverhalt"]}).json()
    assert c.get("/status").json()["released"] is False  # Vorschau ist keine Freigabe
    assert p["rows"][0]["cells"]["mandant"]["spans"]

    r = c.post("/release", json={"preview_id": p["id"], "actor": "pruefer@example.org", "confirmed": True}).json()
    assert r["row_count"] == 5 and r["columns"] == ["mandant", "sachverhalt"]
    t = c.get("/tables").json()
    assert t["released"] and t["visible"]["columns"] == ["zeile", "mandant", "sachverhalt"]

    token = t["visible"]["rows"][0][1]
    back = c.post("/retranslate", json={"text": f"{token} hat gute Chancen."}).json()
    assert back["text"] == "Max Mustermann hat gute Chancen."

    c.post("/revoke")
    assert c.get("/status").json()["released"] is False


def test_errors(tmp_path, detector, monkeypatch):
    monkeypatch.setattr("arca.service.ArcaAnonymizer", lambda conn, secret: ArcaAnonymizer(conn, secret, detector))
    c = client(tmp_path, detector)
    assert c.post("/preview", json={"columns": ["passwort"]}).status_code == 400
    assert c.post("/preview", json={"columns": []}).status_code == 400
    assert c.post("/release", json={"preview_id": "x"}).status_code == 409


def test_review_prompt_and_audit_endpoints(tmp_path, detector, monkeypatch):
    monkeypatch.setattr("arca.service.ArcaAnonymizer", lambda conn, secret: ArcaAnonymizer(conn, secret, detector))
    c = client(tmp_path, detector)
    p = c.post("/preview", json={"columns": ["mandant"], "options": {"dates": "year"}}).json()
    assert p["options"] == {"dates": "year", "money": "range"}
    # ohne Bestätigung keine Freigabe
    assert c.post("/release", json={"preview_id": p["id"], "actor": "a@example.org"}).status_code == 409
    assert c.get("/status").json()["released"] is False

    r = c.post("/pseudonymize", json={"text": "Was ist mit Max Mustermann?"}).json()
    assert "Mustermann" not in r["text"] and r["text"].startswith("Was ist mit PERSON_")

    assert c.post("/audit", json={"action": "terminal_unlock", "actor": "a@example.org"}).status_code == 200
    assert c.post("/audit", json={"action": "release", "actor": "a@example.org"}).status_code == 400
    log = c.get("/tables").json()["audit"]
    assert log[0]["action"] == "terminal_unlock" and log[0]["actor"] == "a@example.org"
