import json

import httpx
import pytest

from cato.accounts import DEFAULT_ORG, Principal
from cato.audit import AuditLog
from cato.classify import Classifier
from cato.detect import Detector
from cato.pipeline import Pipeline
from cato.policy import builtin_policy
from cato.prompts import (
    LangfusePromptBackend, LocalPromptBackend, PromptError, PromptService, backend_from_env,
)

DETECTOR = Detector()
ALICE = Principal("api_key", DEFAULT_ORG, "user", "key_alice", "alice")
OTHER = Principal("api_key", "org_other", "user", "key_other", "other")
GOOD = "Du bist ein freundlicher Support-Assistent. Sprich {{customer_name}} mit Sie an."


def service(backend=None) -> PromptService:
    pipeline = Pipeline(builtin_policy("support-default"), detector=DETECTOR, classifier=Classifier())
    return PromptService(backend or LocalPromptBackend(), DETECTOR, Classifier(),
                         lambda t: pipeline.protect(t, "external").text, AuditLog())


def test_versions_labels_history_diff():
    svc = service()
    v1 = svc.create(ALICE, "support-bot", GOOD, {"temperature": 0.2}, "first")
    assert v1["version"] == 1 and v1["draft"] and v1["labels"] == ["latest"] and not v1["protected"]
    v2 = svc.create(ALICE, "support-bot", GOOD + " Antworte kurz.", None, "shorter")
    assert v2["version"] == 2
    assert svc.set_label(ALICE, "support-bot", 1, "production") == {
        "name": "support-bot", "label": "production", "version": 1, "previous_version": None}
    assert svc.get(DEFAULT_ORG, "support-bot", label="production")["version"] == 1
    assert svc.get(DEFAULT_ORG, "support-bot")["version"] == 2  # creating never moves a label
    moved = svc.set_label(ALICE, "support-bot", 2, "production")
    assert moved["previous_version"] == 1
    hist = svc.history(DEFAULT_ORG, "support-bot")
    assert [h["version"] for h in hist] == [2, 1] and hist[0]["labels"] == ["production", "latest"]
    d = svc.diff(DEFAULT_ORG, "support-bot", 1, 2)
    assert "+Du bist" in d["diff"] and "Antworte kurz" in d["diff"] and d["config_changed"]
    assert svc.list(DEFAULT_ORG) == [{"name": "support-bot", "latest_version": 2, "versions": 2,
                                      "labels": {"production": 2}, "updated_at": hist[0]["created_at"]}]


def test_chat_prompts():
    svc = service()
    v = svc.create(ALICE, "chat-bot", [{"role": "system", "content": GOOD}, {"role": "user", "content": "{{q}}"}])
    assert v["type"] == "chat" and v["prompt"][1] == {"role": "user", "content": "{{q}}"}


@pytest.mark.parametrize("text,msg", [
    ("Beispiel: Max Mustermann, max@example.org", "sensitive data"),
    ("Kunde mit IBAN DE89 3704 0044 0532 0130 00", "sensitive data"),
    ("Antworte wie bei PERSON_001.", "placeholders"),
    ("Zahlung [REDACTED] prüfen", "placeholders"),
    ("   ", "empty"),
])
def test_writes_are_checked(text, msg):
    svc = service()
    with pytest.raises(PromptError, match=msg) as exc:
        svc.create(ALICE, "bot", text)
    assert "Mustermann" not in str(exc.value) and "DE89" not in str(exc.value)
    assert svc.list(DEFAULT_ORG) == []


def test_example_context_does_not_whitelist_names():
    with pytest.raises(PromptError, match="person"):
        service().create(ALICE, "bot", "Example answer for the customer Max Mustermann: thanks for waiting.")
    ok = service().create(ALICE, "bot", "Du arbeitest für die Beispiel GmbH in Berlin. Preise ab 9,90 Euro.")
    assert ok["version"] == 1


def test_statistical_single_words_only_warn():
    svc = service()
    v = svc.create(ALICE, "bot", "Du bist Lisa, die Support-Assistentin. Nenne den Kunden beim Namen. Kurz.")
    assert v["version"] == 1 and v["warnings"] and all("person" in w for w in v["warnings"])
    entry = svc.audit.list(DEFAULT_ORG)[0]
    assert entry["after"]["warnings"] == ["person"] and "Lisa" not in json.dumps(entry)
    with pytest.raises(PromptError, match="person"):
        svc.create(ALICE, "bot", "Antworte wie bei Max Mustermann.")


def test_note_config_name_and_label_validation():
    svc = service()
    with pytest.raises(PromptError, match="config"):
        svc.create(ALICE, "bot", GOOD, {"example": "Herr Max Mustermann"})
    with pytest.raises(PromptError, match="note"):
        svc.create(ALICE, "bot", GOOD, None, "fix for max.mustermann@example.org")
    with pytest.raises(PromptError, match="name"):
        svc.create(ALICE, "../bot", GOOD)
    svc.create(ALICE, "bot", GOOD)
    for label in ("latest", "Production", "x" * 40):
        with pytest.raises(PromptError, match="label"):
            svc.set_label(ALICE, "bot", 1, label)
    with pytest.raises(PromptError) as exc:
        svc.set_label(ALICE, "bot", 9, "production")
    assert exc.value.status == 404


def test_reads_of_unsafe_prompts_are_protected():
    backend = LocalPromptBackend()
    backend.create(DEFAULT_ORG, "legacy", "text", "Grüße Herrn Max Mustermann (max@example.org).", {}, None, "import")
    out = service(backend).get(DEFAULT_ORG, "legacy")
    assert out["protected"] and "Mustermann" not in json.dumps(out) and "PERSON_001" in out["prompt"]


def test_org_isolation_and_audit():
    svc = service()
    svc.create(ALICE, "bot", GOOD)
    assert svc.list(OTHER.org_id) == []
    with pytest.raises(PromptError):
        svc.get(OTHER.org_id, "bot")
    svc.set_label(ALICE, "bot", 1, "production")
    actions = [e["action"] for e in svc.audit.list(DEFAULT_ORG)]
    assert actions == ["label", "create"] and svc.audit.verify(DEFAULT_ORG)["ok"]


def langfuse_mock(store: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/api/public/v2/prompts" and method == "POST":
            body = json.loads(request.content)
            versions = store.setdefault(body["name"], [])
            v = {**body, "version": len(versions) + 1, "labels": body.get("labels", [])}
            versions.append(v)
            return httpx.Response(201, json=v)
        if path == "/api/public/v2/prompts":
            name = request.url.params.get("name")
            data = [{"name": n, "versions": [v["version"] for v in vs]} for n, vs in store.items()
                    if name is None or n == name]
            return httpx.Response(200, json={"data": data, "meta": {"totalPages": 1}})
        parts = path.split("/")
        if len(parts) == 6 and method == "GET":
            versions = store.get(parts[5])
            if not versions:
                return httpx.Response(404)
            if "version" in request.url.params:
                v = next((x for x in versions if x["version"] == int(request.url.params["version"])), None)
            else:
                label = request.url.params.get("label")
                v = versions[-1] if label == "latest" else next(
                    (x for x in versions if label in x["labels"]), None)
            return httpx.Response(200, json=v) if v else httpx.Response(404)
        if len(parts) == 8 and method == "PATCH":
            labels = json.loads(request.content)["newLabels"]
            for v in store[parts[5]]:
                v["labels"] = [lbl for lbl in v["labels"] if lbl not in labels]
                if v["version"] == int(parts[7]):
                    v["labels"] = labels
            return httpx.Response(200, json={})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_langfuse_backend_round_trip():
    store: dict = {}
    svc = service(LangfusePromptBackend("https://lf.internal", "pk", "sk", transport=langfuse_mock(store)))
    svc.create(ALICE, "support-bot", GOOD, None, "v1")
    svc.create(ALICE, "support-bot", GOOD + " Kurz.")
    assert store["support-bot"][0]["labels"] == [] and store["support-bot"][0]["commitMessage"] == "v1"
    svc.set_label(ALICE, "support-bot", 1, "production")
    assert svc.get(DEFAULT_ORG, "support-bot", label="production")["version"] == 1
    assert svc.set_label(ALICE, "support-bot", 2, "production")["previous_version"] == 1
    assert [h["version"] for h in svc.history(DEFAULT_ORG, "support-bot")] == [2, 1]
    assert svc.list(DEFAULT_ORG)[0]["latest_version"] == 2
    with pytest.raises(PromptError, match="default organization"):
        svc.list(OTHER.org_id)


def test_backend_factory(tmp_path):
    assert backend_from_env({}) is None
    assert backend_from_env({"CATO_PROMPTS": "local", "CATO_PROMPTS_DB": str(tmp_path / "p.db")}).kind == "local"
    lf = backend_from_env({"CATO_PROMPTS": "langfuse", "CATO_SOURCE": "langfuse", "CATO_SOURCE_URL": "https://lf",
                           "CATO_SOURCE_PUBLIC_KEY": "pk", "CATO_SOURCE_SECRET_KEY": "sk"})
    assert lf.kind == "langfuse"
    with pytest.raises(PromptError):
        backend_from_env({"CATO_PROMPTS": "langfuse"})
    with pytest.raises(PromptError, match="unknown"):
        backend_from_env({"CATO_PROMPTS": "git"})


def test_notes_and_config_from_outside_are_protected_on_read():
    backend = LocalPromptBackend()
    backend.create(DEFAULT_ORG, "lf", "text", GOOD, {"example_customer": "max.mustermann@example.org"},
                   "Fix für Max Mustermann (max.mustermann@example.org)", "import")
    svc = service(backend)
    out = svc.get(DEFAULT_ORG, "lf")
    assert out["protected"] and out["config"] == {"withheld": "config contains sensitive data"}
    assert "Mustermann" not in json.dumps(out) and "EMAIL_001" in out["note"]
    assert "Mustermann" not in json.dumps(svc.history(DEFAULT_ORG, "lf"))
