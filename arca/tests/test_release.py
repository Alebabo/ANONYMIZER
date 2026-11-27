"""Ohne Freigabe ist visible.db leer; nach der Freigabe enthält sie keinen Originalwert aus dem Seed."""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from arca import vault_db
from arca.release import ReleaseError, audit_log, release, released, revoke

ALL = list(vault_db.COLUMNS)


def visible_dump(path) -> tuple[list[str], list[str]]:
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        cells = [str(v) for t in tables for row in conn.execute(f'SELECT * FROM "{t}"') for v in row]
        return tables, cells
    finally:
        conn.close()


def seed_secrets() -> list[str]:
    """Alle identifizierenden Werte aus dem Seed, inklusive Vor- und Nachnamen einzeln."""
    values = set()
    for row in vault_db.SEED:
        for col in ("mandant", "unternehmen", "gegner", "aktenzeichen", "ort"):
            values.add(row[col])
        for col in ("mandant", "gegner"):
            if not re.search(r"\b(GmbH|AG|KG)\b", row[col]):  # Personen: Vor- und Nachname einzeln
                values.update(row[col].split())
    return sorted(values)


def contains_word(blob: str, value: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", blob, re.IGNORECASE) is not None


def test_visible_empty_without_release(paths, arca):
    _, visible = paths
    assert visible_dump(visible) == ([], [])
    arca.preview(ALL)  # Vorschau schreibt nichts nach A
    assert visible_dump(visible) == ([], [])
    assert not released(visible)


def test_no_original_names_after_release(paths, vault, arca):
    _, visible = paths
    preview = arca.preview(ALL)
    release(vault, visible, preview["id"])
    tables, cells = visible_dump(visible)
    assert tables == ["mandate"]
    blob = "\n".join(cells)
    leaked = [v for v in seed_secrets() if contains_word(blob, v)]
    assert leaked == []
    # Streitwert bleibt lesbar, Klartext des Sachverhalts ist anonymisiert
    assert "500.000 €" in cells


def test_only_selected_columns(paths, vault, arca):
    _, visible = paths
    release(vault, visible, arca.preview(["streitwert", "sachverhalt"])["id"])
    conn = sqlite3.connect(visible)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(mandate)")]
    conn.close()
    assert cols == ["zeile", "streitwert", "sachverhalt"]
    _, cells = visible_dump(visible)
    assert not any("Mustermann" in c for c in cells)  # Mandant nicht gewählt, trotzdem im Freitext ersetzt


def test_release_blocks_on_leak(paths, vault, arca):
    _, visible = paths
    preview = arca.preview(["sachverhalt"])
    payload = preview["rows"]
    payload[0]["cells"]["sachverhalt"]["value"] = "Max Mustermann klagt."
    vault.execute("UPDATE preview SET payload = ? WHERE id = ?", (json.dumps(payload), preview["id"]))
    with pytest.raises(ReleaseError):
        release(vault, visible, preview["id"])
    assert visible_dump(visible) == ([], [])


def test_audit_log(paths, vault, arca):
    _, visible = paths
    release(vault, visible, arca.preview(["mandant", "streitwert"])["id"])
    revoke(vault, visible)
    log = audit_log(vault)
    assert [e["action"] for e in log] == ["revoke", "release"]
    assert log[1]["columns"] == ["mandant", "streitwert"] and log[1]["row_count"] == len(vault_db.SEED)
    assert log[1]["created_at"] > 0
    assert visible_dump(visible) == ([], [])


def test_unknown_preview(paths, vault):
    with pytest.raises(ReleaseError):
        release(vault, paths[1], "nope")
