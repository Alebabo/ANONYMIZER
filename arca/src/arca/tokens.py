"""Arca-Tokens: ``PREFIX_`` + HMAC-SHA256(ARCA_SECRET, normalisierter Wert), gekürzt auf 8 Hex-Zeichen.

* Deterministisch: gleicher Wert -> gleiches Token, auch nach Neuaufbau der Datenbanken.
* Kein einfacher Hash: ohne ARCA_SECRET lässt sich ein Token nicht aus einem geratenen Namen nachrechnen.
* Der Hash läuft nur über den Wert, nicht über den Typ: wird "Muster GmbH" einmal als Firma und einmal als
  Ort erkannt, unterscheiden sich nur die Präfixe, der Hash-Teil bleibt gleich.
* Das Mapping Token -> Original liegt ausschließlich in vault.db (Tabelle ``token_map``).

``ArcaVault`` erfüllt das ``Vault``-Protocol von anonymizer-core, damit die vorhandene Engine
(``OpenAnonymizer``: Ersetzung, Sweep, Leak-Prüfung) unverändert die Arca-Tokens vergibt.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from anonymizer.vault import normalize

TOKEN_HEX = 8
TOKEN_RE = re.compile(r"\b[A-Z]+(?:_[A-Z]+)*_[0-9a-f]{%d}\b" % TOKEN_HEX)


class TokenCollision(RuntimeError):
    pass


def make_token(secret: bytes, prefix: str, value: str) -> str:
    digest = hmac.new(secret, normalize(value).encode(), hashlib.sha256).hexdigest()
    return f"{prefix}_{digest[:TOKEN_HEX]}"


class ArcaVault:
    """Vault-Protocol über vault.db. Namespaces werden nicht gebraucht (ein Arca = ein Bestand)."""

    def __init__(self, conn: sqlite3.Connection, secret: bytes) -> None:
        self._conn = conn
        self._secret = secret
        self._lock = threading.RLock()
        # Nachname -> voller Name (normalisiert), gesetzt von der Vorschau: "Albrecht" bekommt das Token
        # von "Jonas Albrecht".
        self.aliases: dict[str, str] = {}

    def _store(self, entity_type: str, value: str, prefix: str) -> str:
        if prefix == "PERSON":
            value = self.aliases.get(normalize(value), value)
        token = make_token(self._secret, prefix, value)
        with self._lock:
            row = self._conn.execute("SELECT value FROM token_map WHERE token = ?", (token,)).fetchone()
            if row is None:
                self._conn.execute("INSERT INTO token_map (token, value, entity_type, created_at) VALUES (?, ?, ?, ?)",
                                   (token, value, entity_type, time.time()))
            elif normalize(row["value"]) != normalize(value):
                raise TokenCollision(f"Token {token} ist bereits einem anderen Wert zugeordnet")
        return token

    # -- Vault-Protocol -------------------------------------------------
    def pseudonym(self, namespace: str, entity_type: str, value: str, prefix: str) -> str:
        return self._store(entity_type, value, prefix)

    def token(self, namespace: str, entity_type: str, value: str) -> str:
        return self._store(entity_type, value, "TKN")

    def resolve(self, namespace: str, placeholder: str) -> str | None:
        row = self._conn.execute("SELECT value FROM token_map WHERE token = ?", (placeholder,)).fetchone()
        return row["value"] if row else None

    @contextmanager
    def batch(self) -> Iterator[None]:
        with self._lock:
            yield
            self._conn.commit()

    # -- Zurückübersetzen (nur UI) --------------------------------------
    def retranslate(self, text: str) -> tuple[str, list[dict]]:
        """Tokens im Text durch Klarnamen ersetzen. Gibt Text und ersetzte Stellen (Offsets im Ergebnis) zurück."""
        out: list[str] = []
        spans: list[dict] = []
        cursor = pos = 0
        for m in TOKEN_RE.finditer(text):
            value = self.resolve("", m.group(0))
            if value is None:
                continue
            out.append(text[cursor:m.start()])
            pos += m.start() - cursor
            out.append(value)
            spans.append({"start": pos, "end": pos + len(value), "token": m.group(0)})
            pos += len(value)
            cursor = m.end()
        out.append(text[cursor:])
        return "".join(out), spans
