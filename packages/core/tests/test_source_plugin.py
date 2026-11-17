"""Plugin sources (ANONYMIZER_SOURCE=python) and source KPIs."""
import json

import pytest

from anonymizer.accounts import DEFAULT_ORG, Principal
from anonymizer.sources import SourceError, source_from_env
from tests.test_conversations import service

ALICE = Principal("api_key", DEFAULT_ORG, "user", "key_alice", "alice")

PLUGIN = '''
from anonymizer.sources import Conversation, ConversationHead, Message, Page

class Src:
    kind = "fake"
    def __init__(self, env, timeout, transport):
        self.url = env["ANONYMIZER_SOURCE_URL"]
    def list(self, since=None, until=None, limit=50, cursor=None, tag=None):
        return Page(data=[ConversationHead(id="s1", created_at=1762905600)], next_cursor=None)
    def get(self, source_id):
        return Conversation(id=source_id, created_at=1762905600,
                            messages=[Message(role="user", content="Ich bin Max Mustermann.")])
    def describe(self):
        return {"kind": self.kind, "location": self.url}
    def kpis(self, since, until):
        return {"range": {"from": "2026-11-01", "to": "2026-11-14"},
                "sessions_per_day": [{"date": "01.11.2026", "count": 12}, {"date": "02.11.2026", "count": 7}],
                "solving_rate_per_week": [{"week": "2026-W45", "rate": "0.61"}],
                "top_question": "Mein Name ist Max Mustermann, max.mustermann@example.org",
                "Max Mustermann": 3}
'''


@pytest.fixture
def plugin(tmp_path):
    path = tmp_path / "src_plugin.py"
    path.write_text(PLUGIN, encoding="utf-8")
    return source_from_env({"ANONYMIZER_SOURCE": "python", "ANONYMIZER_SOURCE_CLASS": f"{path}:Src",
                            "ANONYMIZER_SOURCE_URL": "https://example.test"})


def test_plugin_source_is_loaded(plugin):
    assert plugin.describe() == {"kind": "fake", "location": "https://example.test"}


@pytest.mark.parametrize("spec", ["", "missing.py:Src", "nofile"])
def test_plugin_spec_errors(spec):
    with pytest.raises(SourceError):
        source_from_env({"ANONYMIZER_SOURCE": "python", "ANONYMIZER_SOURCE_CLASS": spec})


def test_kpis_keep_aggregates_and_drop_personal_strings(plugin):
    out = service(plugin).kpis(ALICE)
    k = out["kpis"]
    assert k["sessions_per_day"][0] == {"date": "01.11.2026", "count": 12}
    assert k["solving_rate_per_week"][0] == {"week": "2026-W45", "rate": "0.61"}
    assert k["top_question"] == "[REDACTED]"
    text = json.dumps(out, ensure_ascii=False)
    assert "Mustermann" not in text and "example.org" not in text


def test_kpis_need_a_source_that_provides_them(tmp_path):
    from anonymizer.conversations import ConversationError
    from anonymizer.sources import JsonlSource

    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps({"id": "a", "created_at": 1, "messages": []}) + "\n", encoding="utf-8")
    with pytest.raises(ConversationError):
        service(JsonlSource(p)).kpis(ALICE)
