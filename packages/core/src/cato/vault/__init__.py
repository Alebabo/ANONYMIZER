"""Re-identification vault.

Stores the mapping between placeholders/tokens and original values,
encrypted with AES-256-GCM. Design rules:

* The key never lives next to the data. It comes from the environment
  (``CATO_VAULT_KEY``) or a key management system, not from the vault file.
* Lookups use an HMAC index, so the storage never contains plaintext
  values, not even for "does this value already have a pseudonym?".
* Namespaces (e.g. one per client matter) are isolated: a placeholder from
  one namespace can never be resolved in another. Namespace names are
  stored as HMACs as well.
* Nothing in this module is ever part of an anonymization result. The
  vault object stays inside the trusted boundary; the gateway only sees
  the transformed text.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ENV_KEY = "CATO_VAULT_KEY"


class VaultError(RuntimeError):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(data: str) -> bytes:
    return base64.b64decode(data.encode())


def normalize(value: str) -> str:
    """Canonical form for lookups: NFC, case-folded, whitespace collapsed."""
    value = unicodedata.normalize("NFC", value).casefold()
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class VaultKey:
    """Master key; derives separate encryption and index keys via HKDF."""

    master: bytes

    def __post_init__(self) -> None:
        if len(self.master) != 32:
            raise VaultError("vault key must be 32 bytes")

    @classmethod
    def generate(cls) -> "VaultKey":
        return cls(secrets.token_bytes(32))

    @classmethod
    def from_b64(cls, value: str) -> "VaultKey":
        try:
            return cls(base64.b64decode(value.encode(), validate=True))
        except (ValueError, TypeError) as exc:
            raise VaultError("vault key is not valid base64") from exc

    @classmethod
    def from_env(cls, name: str = ENV_KEY) -> "VaultKey":
        value = os.environ.get(name)
        if not value:
            raise VaultError(f"environment variable {name} is not set")
        return cls.from_b64(value)

    def to_b64(self) -> str:
        return _b64(self.master)

    def _derive(self, info: bytes) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(self.master)

    @property
    def enc_key(self) -> bytes:
        return self._derive(b"cato-vault-encryption-v1")

    @property
    def index_key(self) -> bytes:
        return self._derive(b"cato-vault-index-v1")

    def __repr__(self) -> str:  # never print key material
        return "VaultKey(***)"


class Vault(Protocol):
    def pseudonym(self, namespace: str, entity_type: str, value: str, prefix: str) -> str: ...
    def token(self, namespace: str, entity_type: str, value: str) -> str: ...
    def resolve(self, namespace: str, placeholder: str) -> str | None: ...


class InMemoryVault:
    """Encrypted vault held in memory. ``FileVault`` adds persistence."""

    def __init__(self, key: VaultKey) -> None:
        self._enc = AESGCM(key.enc_key)
        self._index_key = key.index_key
        self._lock = threading.RLock()
        self._batching = 0
        self._dirty = False
        # ns_hash -> {"entries": {index: {...}}, "tokens": {placeholder: index}, "counters": {prefix: n}}
        self._data: dict[str, dict] = {}

    # -- internals -------------------------------------------------------
    def _mac(self, *parts: str) -> str:
        msg = "\x1f".join(parts).encode()
        return hmac.new(self._index_key, msg, hashlib.sha256).hexdigest()

    def _ns(self, namespace: str) -> tuple[str, dict]:
        if not namespace:
            raise VaultError("namespace is required")
        ns_hash = self._mac("namespace", namespace)
        return ns_hash, self._data.setdefault(ns_hash, {"entries": {}, "tokens": {}, "counters": {}})

    def _encrypt(self, ns_hash: str, placeholder: str, value: str) -> dict:
        nonce = secrets.token_bytes(12)
        ct = self._enc.encrypt(nonce, value.encode(), f"{ns_hash}:{placeholder}".encode())
        return {"nonce": _b64(nonce), "ct": _b64(ct)}

    def _decrypt(self, ns_hash: str, placeholder: str, entry: dict) -> str:
        try:
            return self._enc.decrypt(_unb64(entry["nonce"]), _unb64(entry["ct"]),
                                     f"{ns_hash}:{placeholder}".encode()).decode()
        except InvalidTag as exc:
            raise VaultError("vault entry cannot be decrypted (wrong key or tampered data)") from exc

    def _store(self, namespace: str, entity_type: str, value: str, make_placeholder) -> str:
        with self._lock:
            ns_hash, ns = self._ns(namespace)
            index = self._mac("value", namespace, entity_type, normalize(value))
            if index in ns["entries"]:
                return ns["entries"][index]["placeholder"]
            placeholder = make_placeholder(ns)
            ns["entries"][index] = {"placeholder": placeholder, "type": entity_type,
                                    **self._encrypt(ns_hash, placeholder, value)}
            ns["tokens"][placeholder] = index
            self._dirty = True
            if not self._batching:
                self._flush()
            return placeholder

    def _flush(self) -> None:
        if self._dirty:
            self._persist()
            self._dirty = False

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Persist once on exit instead of after every new entry.

        Entries are written before the block is left, i.e. before a caller
        can hand out the placeholders created inside it.
        """
        with self._lock:
            self._batching += 1
            try:
                yield
            finally:
                self._batching -= 1
                if not self._batching:
                    self._flush()

    def _persist(self) -> None:  # overridden by FileVault
        pass

    # -- public API ------------------------------------------------------
    def pseudonym(self, namespace: str, entity_type: str, value: str, prefix: str) -> str:
        """Stable placeholder such as ``PERSON_001`` for ``value`` in ``namespace``."""
        def make(ns: dict) -> str:
            n = ns["counters"].get(prefix, 0) + 1
            ns["counters"][prefix] = n
            return f"{prefix}_{n:03d}"
        return self._store(namespace, entity_type, value, make)

    def token(self, namespace: str, entity_type: str, value: str) -> str:
        """Random, opaque, stable token such as ``TKN_3f9a0c1b2d4e``."""
        def make(ns: dict) -> str:
            while True:
                candidate = f"TKN_{secrets.token_hex(6)}"
                if candidate not in ns["tokens"]:
                    return candidate
        return self._store(namespace, entity_type, value, make)

    def resolve(self, namespace: str, placeholder: str) -> str | None:
        with self._lock:
            ns_hash, ns = self._ns(namespace)
            index = ns["tokens"].get(placeholder)
            if index is None:
                return None
            return self._decrypt(ns_hash, placeholder, ns["entries"][index])

    def known_placeholders(self, namespace: str) -> set[str]:
        with self._lock:
            return set(self._ns(namespace)[1]["tokens"])


class FileVault(InMemoryVault):
    """Vault persisted as a JSON file (encrypted values, HMAC index, 0600).

    Suitable for single-node self-hosting. The key must be provided
    separately and must not be stored in the same location.
    """

    VERSION = 1

    def __init__(self, path: str | Path, key: VaultKey) -> None:
        super().__init__(key)
        self.path = Path(path)
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") != self.VERSION:
                raise VaultError(f"unsupported vault version {raw.get('version')}")
            self._data = raw["namespaces"]

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": self.VERSION, "namespaces": self._data}, separators=(",", ":"))
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".vault-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())  # a lost mapping makes sent pseudonyms irreversible
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


__all__ = ["ENV_KEY", "FileVault", "InMemoryVault", "Vault", "VaultError", "VaultKey", "normalize"]
