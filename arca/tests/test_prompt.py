"""Fragen an Claude werden mit denselben Tokens pseudonymisiert wie die Daten in A."""

from __future__ import annotations

from arca.release import release


def test_prompt_uses_same_tokens_as_visible(paths, vault, arca):
    preview = arca.preview(["mandant", "unternehmen"])
    release(vault, paths[1], preview["id"], "pruefer@example.org", True)
    row = preview["rows"][1]["cells"]  # Sabine Keller / Keller Logistik AG
    out = arca.pseudonymize("Wie stehen die Chancen von Frau Keller und der Keller Logistik AG?")
    assert "Keller" not in out["value"]
    assert row["unternehmen"]["value"] in out["value"]
    assert row["mandant"]["value"] in out["value"]  # Nachname allein -> Token des vollen Namens


def test_prompt_new_name_gets_token_and_hint(arca):
    out = arca.pseudonymize("Ruf bitte Herrn Dr. Klaus Vehrenkamp in Lüneburg an.")
    assert "Vehrenkamp" not in out["value"]
    types = {s["type"] for s in out["spans"]}
    assert "person" in types


def test_prompt_is_retranslatable(arca):
    out = arca.pseudonymize("Was schuldet Erika Schneider?")
    text, _ = arca.vault.retranslate(out["value"])
    assert text == "Was schuldet Erika Schneider?"


def test_hint_for_missed_place(arca):
    out = arca.cell("Der Zeuge aus Lüneburg bestätigt das.", "text", arca.known_values([]))
    checks = [out["value"][s["start"]:s["end"]] for s in out["spans"] if s["type"] == "check"]
    assert checks == ["Lüneburg"] or "Lüneburg" not in out["value"]
