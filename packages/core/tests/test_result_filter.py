"""Structured-result filter used by the playground (synthetic data only)."""

from __future__ import annotations

import json

import mcp_types as types
import pytest

from anonymizer.pipeline import Pipeline
from anonymizer.policy import builtin_policy
from anonymizer.result_filter import DEFAULT_FIELD_HINTS, WITHHELD, KnownValues, ResultFilter
from anonymizer.tracing import TraceStore
from anonymizer.vault import InMemoryVault, VaultKey

SECRETS = ["Mustermann", "Musterfrau", "max.mustermann@example.org", "erika@example.com", "1234567",
           "98765432", "DE89", "0532 0130", "Depression", "Hauptstraße", "Beispiel"]


def leaks(text: str) -> list[str]:
    return [s for s in SECRETS if s in text]


def text_result(*items) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=i if isinstance(i, str) else
                                                           json.dumps(i, ensure_ascii=False)) for i in items])


@pytest.fixture(scope="module")
def pipeline():
    return Pipeline(builtin_policy("support-default"), vault=InMemoryVault(VaultKey.generate()))


def make_filter(pipeline, observe=False, **kw):
    return ResultFilter(pipeline, "external", "filter:test", observe=observe, hints=DEFAULT_FIELD_HINTS, **kw)


ROWS = [{"id": 1, "vorname": "Max", "nachname": "Mustermann", "email": "max.mustermann@example.org",
         "telefon": "+49 170 1234567", "iban": "DE89 3704 0044 0532 0130 00", "segment": "privat",
         "notiz": "Kundin ist wegen einer Depression krankgeschrieben."},
        {"id": 2, "vorname": "Erika", "nachname": "Musterfrau", "email": "erika@example.com",
         "telefon": "030 98765432", "iban": "DE02 1203 0000 0000 2020 51", "segment": "premium", "notiz": "ok"}]


# --- filter ---------------------------------------------------------------------------------

def test_json_rows_are_protected_field_by_field(pipeline):
    out, report = make_filter(pipeline).apply(text_result(ROWS))
    data = json.loads(out.content[0].text)
    assert not leaks(out.content[0].text)
    assert list(data[0]) == list(ROWS[0])                 # keys stay readable
    assert data[0]["segment"] == "privat" and data[0]["id"] == 1
    assert data[0]["notiz"] == WITHHELD                   # special category -> local_only for external
    assert data[0]["vorname"].startswith("PERSON_") and data[0]["email"].startswith("EMAIL_")
    assert report.withheld == 1 and report.hinted >= 1
    trace = report.trace()
    assert trace.fields["$[].email"] == {"email": 2} and "health_data" in trace.entity_counts
    stored = TraceStore().add(trace)                      # content traces are off by default
    assert not leaks(stored.model_dump_json())            # stored traces carry types and paths only


def test_same_value_same_placeholder_across_calls(pipeline):
    f = make_filter(pipeline)
    a = json.loads(f.apply(text_result({"email": "max.mustermann@example.org"}))[0].content[0].text)
    b = json.loads(make_filter(pipeline).apply(text_result({"mail": "max.mustermann@example.org"}))[0]
                   .content[0].text)
    assert a["email"] == b["mail"]


def test_known_values_are_found_in_free_text(pipeline):
    f = make_filter(pipeline)
    f.apply(text_result({"vorname": "Jonas", "nachname": "Beispiel"}))
    out, report = f.apply(text_result({"text": "Gruß, Jonas Beispiel"}))
    assert "Beispiel" not in out.content[0].text and report.learned + len(report.parts) > 0


def test_identifiers_and_keys_are_not_over_redacted(pipeline):
    out, _ = make_filter(pipeline).apply(text_result({"customers": ["id", "vorname", "telefon", "iban"],
                                                      "status": "open"}))
    assert json.loads(out.content[0].text) == {"customers": ["id", "vorname", "telefon", "iban"], "status": "open"}


def test_dates_amounts_and_numbers_in_widget_json(pipeline):
    msg = json.dumps({"type": "ANSWER_TEXT", "data": {"text": "Ihr Kontostand: 1.234,56 €, Vorgang 88123456"},
                      "timestamp": "2026-11-09T23:23:34.118546047Z"})
    rows = [{"Zeitpunkt": "19.10.2026 00:09", "Nachricht": msg,
             "tx": {"amount": -12.5, "transactionId": "1726431166", "logicalId": 5033872}}]
    out, _ = make_filter(pipeline).apply(text_result(rows))
    row = json.loads(out.content[0].text)[0]
    inner = json.loads(row["Nachricht"])
    assert inner["timestamp"].startswith("DATE_") and "23:23" not in row["Nachricht"]   # whole timestamp
    assert row["Zeitpunkt"].startswith("DATE_") and "00:09" not in row["Zeitpunkt"]
    assert "***56 €" in inner["data"]["text"] and "1.234" not in inner["data"]["text"]  # amount masked
    assert "NUMBER_" in inner["data"]["text"] and "88123456" not in inner["data"]["text"]
    assert row["tx"]["amount"] == "***50"
    assert row["tx"]["transactionId"].startswith("NUMBER_") and row["tx"]["logicalId"] != 5033872
    assert inner["type"] == "ANSWER_TEXT"


def test_data_in_keys_is_protected(pipeline):
    out, _ = make_filter(pipeline).apply(text_result({"max.mustermann@example.org": {"orders": 3}}))
    assert not leaks(out.content[0].text) and "orders" in out.content[0].text


def test_plain_text_and_structured_content(pipeline):
    raw = types.CallToolResult(
        content=[types.TextContent(type="text", text="Kunde Max Mustermann, IBAN DE89 3704 0044 0532 0130 00")],
        structured_content={"result": "Kunde Max Mustermann, IBAN DE89 3704 0044 0532 0130 00"})
    out, report = make_filter(pipeline).apply(raw)
    assert not leaks(out.content[0].text) and not leaks(json.dumps(out.structured_content))
    assert sum(report.trace().entity_counts.values()) == 2  # structured copy not counted twice


def test_non_text_content_is_withheld(pipeline):
    raw = types.CallToolResult(content=[types.ImageContent(type="image", data="aGVsbG8=", mime_type="image/png")])
    out, report = make_filter(pipeline).apply(raw)
    assert out.content[0].type == "text" and "withheld" in out.content[0].text and report.non_text == 1


def test_numbers_under_hinted_keys(pipeline):
    out, _ = make_filter(pipeline).apply(text_result({"telefon": 491701234567, "count": 4}))
    data = json.loads(out.content[0].text)
    assert data["count"] == 4 and "1234567" not in str(data["telefon"])


def test_observe_mode_returns_original_but_reports(pipeline):
    raw = text_result(ROWS)
    out, report = make_filter(pipeline, observe=True).apply(raw)
    assert out is raw
    assert report.trace().entity_counts.get("email") == 2 and report.withheld == 1


def test_oversized_result_is_withheld(pipeline):
    out, _ = make_filter(pipeline, max_chars=10).apply(text_result("Max Mustermann ruft an"))
    assert "withheld" in out.content[0].text and not leaks(out.content[0].text)


# --- review findings ------------------------------------------------------------------------

def test_structured_only_data_is_reported(pipeline):
    raw = types.CallToolResult(content=[types.TextContent(type="text", text="Found 2 rows")],
                               structured_content={"rows": ROWS})
    out, report = make_filter(pipeline).apply(raw)
    assert not leaks(json.dumps(out.structured_content, ensure_ascii=False))
    trace = report.trace()
    assert trace.entity_counts.get("email") == 2 and trace.fields["$.rows[].email"] == {"email": 2}


def test_numbers_without_hint_are_checked(pipeline):
    out, report = make_filter(pipeline).apply(text_result({"card": 4111111111111111, "id": 1234567, "ts": 1731600000,
                                                           "count": 12, "year": 2026}))
    data = json.loads(out.content[0].text)
    assert "4111111111111111" not in out.content[0].text
    assert data["id"].startswith("NUMBER_") and data["ts"].startswith("NUMBER_")   # 4+ digits: placeholder
    assert data["count"] == 12 and data["year"] == 2026                              # small numbers and years stay
    assert report.trace().entity_counts == {"credit_card": 1, "number": 2}


def fresh_pipeline():
    return Pipeline(builtin_policy("support-default"), vault=InMemoryVault(VaultKey.generate()))


def test_ner_batch_only_for_free_text_and_output_unchanged(monkeypatch):
    rows = ROWS + [{"id": 3, "vorname": "Jan", "notiz": "Anruf von Erika Musterfrau aus Köln wegen der Karte."}]
    unbatched = fresh_pipeline()
    monkeypatch.setattr(unbatched.detector, "prefetch", lambda texts, lang: None)
    expected = make_filter(unbatched).apply(text_result(rows))[0].content[0].text

    batched, seen = fresh_pipeline(), []
    real = batched.detector.prefetch
    monkeypatch.setattr(batched.detector, "prefetch", lambda texts, lang: (seen.extend(texts), real(texts, lang)))
    assert make_filter(batched).apply(text_result(rows))[0].content[0].text == expected
    assert rows[2]["notiz"] in seen                                  # free text goes through the batch
    assert not {"Max", "Mustermann", "max.mustermann@example.org", "privat"} & set(seen)  # hinted / identifiers


def test_hinted_value_with_extra_letters_gets_the_full_detector(monkeypatch):
    p, calls = fresh_pipeline(), []
    real = p.detector.scan
    monkeypatch.setattr(p.detector, "scan", lambda text, lang=None: (calls.append(text), real(text, lang))[1])
    make_filter(p).apply(text_result([{"email": "max.mustermann@example.org"}, {"email": "max.mustermann@example.org Max"}]))
    assert calls == ["max.mustermann@example.org Max"]  # the clean value needs rules only


def test_oversized_structured_content_is_withheld(pipeline):
    raw = types.CallToolResult(content=[types.TextContent(type="text", text="ok")],
                               structured_content={"rows": ROWS})
    out, _ = make_filter(pipeline, max_chars=50).apply(raw)
    assert out.structured_content is None and "withheld" in out.content[0].text


def test_known_values_thread_safety():
    import threading

    known, errors = KnownValues(), []

    def work(n):
        try:
            for i in range(300):
                known.add(f"Name{n}x{i}", "person")
                known.find(f"Hallo Name{n}x{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(known.values) == 1200
