import io

import docx
import pytest
from fastapi.testclient import TestClient

from cato.api import create_app
from cato.api.settings import Settings
from cato_sdk import Cato, CatoError, PolicyViolation

USER = "cato_test_user_key_0123456789abcdef"
ADMIN = "cato_test_admin_key_0123456789abcdef"


@pytest.fixture
def app(tmp_path):
    from cato.vault import VaultKey
    return TestClient(create_app(Settings.from_env({
        "CATO_API_KEYS": USER, "CATO_ADMIN_KEYS": ADMIN, "CATO_POLICY_DIR": str(tmp_path / "p"),
        "CATO_ACCOUNTS_DB": ":memory:", "CATO_AUDIT_DB": ":memory:", "CATO_TRACE_DB": ":memory:", "CATO_VAULT_KEY": VaultKey.generate().to_b64(),
        "CATO_VAULT_PATH": str(tmp_path / "v.json")})))


def client(app, key=USER):
    return Cato(api_key=key, base_url="http://testserver", http_client=app)


def test_protect_and_attribute_access(app):
    cato = client(app)
    r = cato.protect("Unser Mandant Herr Max Mustermann bittet um Rückruf.", namespace="m1")
    assert r.allowed and r.text == "Unser Mandant Herr PERSON_001 bittet um Rückruf."
    assert r.decision.policy == "legal-default@v1"
    blocked = cato.protect("Herr Max Mustermann leidet an einer Depression.")
    assert not blocked.allowed and blocked.text is None
    with pytest.raises(PolicyViolation):
        cato.protect("Herr Max Mustermann leidet an einer Depression.", require_allowed=True)


def test_scan_classify_anonymize(app):
    cato = client(app)
    scan = cato.scan("Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00")
    assert {d["entity_type"] for d in scan.detections} >= {"person", "iban"}
    assert cato.classify("IBAN DE89 3704 0044 0532 0130 00").risk == "critical"
    assert cato.anonymize("Herr Max Mustermann", methods={"person": "redact"}).text == "Herr [REDACTED]"


def test_document_roundtrip(app, tmp_path):
    d = docx.Document()
    d.add_paragraph("Unser Mandant Herr Max Mustermann bittet um Rückruf.")
    path = tmp_path / "brief.docx"
    d.save(path)
    r = client(app).protect_document(path)
    assert r.allowed and r.format == "docx"
    assert "PERSON_001" in docx.Document(io.BytesIO(r.content)).paragraphs[0].text


def test_restore_requires_admin(app):
    client(app).protect("Herr Max Mustermann bittet um Rückruf.", namespace="m1")
    with pytest.raises(CatoError) as exc:
        client(app).restore("PERSON_001", "m1")
    assert exc.value.status == 403
    assert client(app, ADMIN).restore("PERSON_001", "m1").text == "Max Mustermann"


def test_policies_traces_metrics(app):
    cato = client(app)
    cato.protect("Herr Max Mustermann bittet um Rückruf.")
    assert cato.policies()[0].name == "legal-default"
    traces = cato.traces()
    assert traces and cato.trace(traces[0].id).route == "/v1/protect"
    assert cato.metrics().requests == 1
    diff = cato.dry_run_policy("IBAN DE89 3704 0044 0532 0130 00",
                               "name: c\nrules:\n  - {entity: iban, action: block}\n")
    assert diff.outcome_after == "block"


def test_errors(app):
    with pytest.raises(CatoError) as exc:
        Cato(api_key="wrong-key-but-long-enough-000", base_url="http://testserver", http_client=app).scan("x")
    assert exc.value.status == 401
    with pytest.raises(ValueError):
        Cato(api_key=None)


def test_conversations_and_prompts(tmp_path):
    import json

    src = tmp_path / "c.jsonl"
    src.write_text(json.dumps({"id": "s1", "created_at": 1762905600, "tags": ["billing"], "messages": [
        {"role": "user", "content": "Mein Name ist Max Mustermann."}]}) + "\n", encoding="utf-8")
    app = TestClient(create_app(Settings.from_env({
        "CATO_API_KEYS": USER, "CATO_ADMIN_KEYS": ADMIN, "CATO_POLICY_DIR": str(tmp_path / "p"),
        "CATO_ACCOUNTS_DB": ":memory:", "CATO_AUDIT_DB": ":memory:", "CATO_TRACE_DB": ":memory:",
        "CATO_SOURCE": "jsonl", "CATO_SOURCE_PATH": str(src), "CATO_CONVERSATIONS_DB": ":memory:",
        "CATO_PROMPTS": "local", "CATO_PROMPTS_DB": ":memory:"})))
    cato = client(app)
    assert cato.sources().conversations["kind"] == "jsonl"
    page = cato.conversations()
    conv = cato.conversation(page.data[0]["id"])
    assert "PERSON_001" in conv.messages[0]["content"] and "Mustermann" not in json.dumps(conv)
    assert cato.conversation_quota().used == 1
    assert cato.conversation_stats("tag").total is None  # 1 conversation < k
    v = cato.create_prompt("bot", "Du bist ein Assistent. Sprich {{name}} an.")
    with pytest.raises(CatoError) as exc:
        cato.create_prompt("bot", "Grüße an Max Mustermann")
    assert exc.value.status == 422
    with pytest.raises(CatoError):
        cato.set_prompt_label("bot", v.version)
    assert client(app, ADMIN).set_prompt_label("bot", v.version).version == 1
    assert cato.prompt("bot", label="production").version == 1
    assert [p.name for p in cato.prompts()] == ["bot"] and len(cato.prompt_history("bot")) == 1
