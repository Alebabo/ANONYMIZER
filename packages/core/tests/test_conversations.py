import json

import pytest

from cato.accounts import DEFAULT_ORG, Principal
from cato.audit import AuditLog
from cato.classify import Classifier
from cato.conversations import ConversationConfig, ConversationError, ConversationService, ConversationStore
from cato.detect import Detector
from cato.pipeline import Pipeline
from cato.policy import builtin_policy
from cato.sources import JsonlSource
from cato.tracing import TraceStore
from cato.vault import FileVault, VaultKey

DETECTOR = Detector()
SECRETS = ["Mustermann", "max.mustermann@example.org", "DE89 3704", "Diabetes", "sess-", "Beispielweg"]
ALICE = Principal("api_key", DEFAULT_ORG, "user", "key_alice", "alice")
BOB = Principal("api_key", DEFAULT_ORG, "user", "key_bob", "bob")
OTHER_ORG = Principal("api_key", "org_other", "user", "key_other", "other")


def conversation(i: int, **extra) -> dict:
    return {
        "id": f"sess-{i:03d}", "created_at": 1762905600 + i * 3600, "language": "de", "channel": "web",
        "tags": ["billing" if i % 2 else "delivery", "Max Mustermann"], "prompt": "support-bot",
        "prompt_version": 11 + i % 2,
        "messages": [
            {"role": "user", "content": "Mein Name ist Max Mustermann, max.mustermann@example.org.",
             "created_at": 1762905600 + i * 3600},
            {"role": "assistant", "content": "Hallo Max Mustermann, wie kann ich helfen?",
             "created_at": 1762905600 + i * 3600 + 125},
            {"role": "user", "content": "Ich habe Diabetes.", "created_at": 1762905600 + i * 3600 + 300},
            {"role": "user", "content": "IBAN DE89 3704 0044 0532 0130 00, Beispielweg 3, 12345 Musterstadt"},
        ],
        **extra,
    }


@pytest.fixture
def source(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text("\n".join(json.dumps(conversation(i)) for i in range(12)) + "\n", encoding="utf-8")
    return JsonlSource(p)


def service(source, vault=None, **cfg):
    policy = builtin_policy("support-default")
    classifier = Classifier()
    return ConversationService(
        source, lambda v: Pipeline(policy, detector=DETECTOR, classifier=classifier, vault=v),
        ConversationStore(), ConversationConfig(**{"min_group": 5, **cfg}), vault=vault,
        traces=TraceStore(), audit=AuditLog(),
    )


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def test_listing_is_metadata_only_with_opaque_ids(source):
    svc = service(source)
    page = svc.list(ALICE, limit=5)
    assert len(page["data"]) == 5 and page["next_cursor"].startswith("cur_")
    head = page["data"][0]
    assert head["id"].startswith("conv_") and head["day"] == "2025-11-12"
    assert head["tags"] in (["billing"], ["delivery"])  # the name tag is dropped
    assert "messages" not in head and not any(s in dump(page) for s in SECRETS)
    # same source id -> same opaque id; cursor continues
    assert svc.list(ALICE, limit=5)["data"][0]["id"] == head["id"]
    nxt = svc.list(ALICE, limit=5, cursor=page["next_cursor"])
    assert {h["id"] for h in nxt["data"]}.isdisjoint({h["id"] for h in page["data"]})


def test_cursor_and_ids_are_org_scoped(source):
    svc = service(source)
    page = svc.list(ALICE, limit=2)
    with pytest.raises(ConversationError, match="cursor"):
        svc.list(OTHER_ORG, cursor=page["next_cursor"])
    with pytest.raises(ConversationError) as exc:
        svc.get(OTHER_ORG, page["data"][0]["id"])
    assert exc.value.status == 404
    with pytest.raises(ConversationError, match="invalid"):
        svc.get(ALICE, "sess-001")


def test_get_protects_every_message(source):
    svc = service(source)
    cid = svc.list(ALICE, limit=1)["data"][0]["id"]
    conv = svc.get(ALICE, cid)
    assert not any(s in dump(conv) for s in SECRETS), dump(conv)
    msgs = conv["messages"]
    assert "PERSON_001" in msgs[0]["content"] and "EMAIL_001" in msgs[0]["content"]
    assert "PERSON_001" in msgs[1]["content"]  # consistent across messages
    assert msgs[2]["content"] is None and msgs[2]["withheld"] and msgs[2]["outcome"] == "local_only"
    assert "[REDACTED]" in msgs[3]["content"]
    assert [m.get("minute") for m in msgs[:3]] == [0, 2, 5] and "minute" not in msgs[3]
    assert conv["withheld"] == 1 and conv["outcome"] == "local_only" and conv["quota"]["used"] == 1
    assert "untrusted" in conv["notice"]


def test_trace_and_audit_without_content(source):
    svc = service(source)
    cid = svc.list(ALICE, limit=1)["data"][0]["id"]
    conv = svc.get(ALICE, cid)
    trace = svc.traces.get(conv["trace_id"])
    assert trace.route == "/v1/conversations" and trace.entity_counts["person"] >= 2
    entry = svc.audit.list(DEFAULT_ORG)[0]
    assert entry["action"] == "read" and entry["resource_type"] == "conversation" and entry["resource_id"] == cid
    assert entry["after"]["withheld"] == 1
    assert not any(s in dump(trace.model_dump()) + dump(entry) for s in SECRETS)
    assert svc.audit.verify(DEFAULT_ORG)["ok"]


def test_daily_quota_per_principal(source):
    svc = service(source, daily_limit=2)
    ids = [h["id"] for h in svc.list(ALICE, limit=3)["data"]]
    svc.get(ALICE, ids[0])
    svc.get(ALICE, ids[1])
    with pytest.raises(ConversationError) as exc:
        svc.get(ALICE, ids[2])
    assert exc.value.status == 429
    assert svc.get(BOB, ids[2])["quota"]["used"] == 1
    assert svc.quota(ALICE) == {"used": 2, "limit": 2, "remaining": 0}


def test_stats_are_k_anonymous(source):
    svc = service(source, min_group=5)
    by_version = svc.stats(ALICE, group_by="prompt_version")
    assert by_version["total"] == 12
    assert {g["key"]: g["conversations"] for g in by_version["groups"]} == {"support-bot@11": 6,
                                                                            "support-bot@12": 6}
    by_day = svc.stats(ALICE, group_by="day")  # 12 conversations, one per hour, on one day
    assert by_day["groups"] == [{"key": "2025-11-12", "conversations": 12, "messages": 48}]
    strict = service(source, min_group=7).stats(ALICE, group_by="tag")
    assert strict["groups"] == [] and strict["suppressed_groups"] == 2
    tiny = service(source, min_group=50).stats(ALICE)
    assert tiny["total"] is None
    with pytest.raises(ConversationError, match="group_by"):
        svc.stats(ALICE, group_by="customer")


def test_persistent_vault_keeps_placeholders_and_allows_admin_restore(source, tmp_path):
    from cato.anonymize import restore
    from cato.conversations import namespace_for

    vault = FileVault(tmp_path / "v.json", VaultKey.generate())
    svc = service(source, vault=vault)
    cid = svc.list(ALICE, limit=1)["data"][0]["id"]
    a, b = svc.get(ALICE, cid), svc.get(BOB, cid)
    assert a["messages"][0]["content"] == b["messages"][0]["content"] and a["stable_placeholders"]
    back = restore(a["messages"][0]["content"], vault, namespace_for(DEFAULT_ORG, cid))
    assert "Max Mustermann" in back.text


def test_long_and_truncated_conversations(tmp_path):
    p = tmp_path / "c.jsonl"
    msgs = [{"role": "user", "content": "x" * 60_000}] + [{"role": "user", "content": "ok"}] * 5
    p.write_text(json.dumps({"id": "s", "created_at": 1, "messages": msgs}) + "\n", encoding="utf-8")
    svc = service(JsonlSource(p), max_messages=3)
    conv = svc.get(ALICE, svc.list(ALICE)["data"][0]["id"])
    assert conv["messages"][0]["content"] is None and conv["truncated"] and len(conv["messages"]) == 3
    assert conv["message_count"] == 6 and conv["outcome"] == "review"
