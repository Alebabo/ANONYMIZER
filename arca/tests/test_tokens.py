"""Gleiche Werte ergeben gleiche Tokens; Tokens hängen vom Schlüssel ab."""

from __future__ import annotations

import hashlib
import hmac

from arca import vault_db
from arca.anonymize import ArcaAnonymizer
from arca.tokens import ArcaVault, make_token

from conftest import SECRET


def test_same_value_same_token():
    assert make_token(SECRET, "PERSON", "Max Mustermann") == make_token(SECRET, "PERSON", "Max Mustermann")
    # Normalisierung: Groß-/Kleinschreibung und Leerzeichen ändern das Token nicht
    assert make_token(SECRET, "PERSON", "max  mustermann") == make_token(SECRET, "PERSON", "Max Mustermann")


def test_different_values_and_keys():
    assert make_token(SECRET, "PERSON", "Max Mustermann") != make_token(SECRET, "PERSON", "Erika Schneider")
    assert make_token(SECRET, "PERSON", "Max Mustermann") != make_token(b"other-secret" * 4, "PERSON", "Max Mustermann")


def test_hmac_not_plain_hash():
    token = make_token(SECRET, "PERSON", "max mustermann")
    plain = hashlib.sha256(b"max mustermann").hexdigest()[:8]
    assert token.endswith(hmac.new(SECRET, b"max mustermann", hashlib.sha256).hexdigest()[:8])
    assert not token.endswith(plain)


def test_tokens_stable_across_rebuild(tmp_path, detector):
    """Zwei unabhängig aufgebaute vault.db mit demselben Schlüssel vergeben dieselben Tokens."""
    def build(name):
        conn = vault_db.connect(tmp_path / name)
        vault_db.seed(conn)
        preview = ArcaAnonymizer(conn, SECRET, detector).preview(list(vault_db.COLUMNS))
        return [{c: v["value"] for c, v in r["cells"].items()} for r in preview["rows"]]
    assert build("a.db") == build("b.db")


def test_same_value_same_token_across_columns(arca):
    preview = arca.preview(["mandant", "sachverhalt"])
    first = preview["rows"][0]["cells"]
    assert first["mandant"]["value"] in first["sachverhalt"]["value"]


def test_surname_gets_full_name_token(arca):
    """"Herr Albrecht" im Freitext bekommt das Token von Gegner "Jonas Albrecht"."""
    row = arca.preview(["gegner", "sachverhalt"])["rows"][2]["cells"]
    assert f"Herr {row['gegner']['value']}" in row["sachverhalt"]["value"]


def test_mapping_only_in_vault(vault, arca):
    arca.preview(["mandant"])
    tokens = {r["token"]: r["value"] for r in vault.execute("SELECT * FROM token_map")}
    assert "Max Mustermann" in tokens.values()
    v = ArcaVault(vault, SECRET)
    text, spans = v.retranslate(f"Mandant {make_token(SECRET, 'PERSON', 'Max Mustermann')} klagt.")
    assert text == "Mandant Max Mustermann klagt."
    assert text[spans[0]["start"]:spans[0]["end"]] == "Max Mustermann"
