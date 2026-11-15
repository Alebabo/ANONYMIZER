"""API settings from environment variables. Fails closed: no keys, no start."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


class SettingsError(RuntimeError):
    pass


@dataclass
class Settings:
    """
    CATO_API_KEYS        comma-separated keys for scan/classify/anonymize/protect (required)
    CATO_ADMIN_KEYS      comma-separated keys for restore and policy management (optional;
                         without them those endpoints are disabled)
    CATO_VAULT_KEY       base64 32-byte vault key (optional; enables reversible pseudonyms)
    CATO_VAULT_PATH      vault file (default ./data/vault.json)
    CATO_POLICY_DIR      policy store directory (default ./data/policies)
    CATO_DEFAULT_POLICY  policy name used when a request names none and no scope applies
    CATO_MAX_CHARS       max characters per text (default 200000)
    CATO_MAX_UPLOAD_BYTES max document upload size (default 25 MiB)
    CATO_ENABLE_NER      "0" to disable spaCy NER (not recommended)
    """

    api_key_hashes: set[str]
    admin_key_hashes: set[str] = field(default_factory=set)
    vault_key: str | None = None
    vault_path: Path = Path("data/vault.json")
    policy_dir: Path = Path("data/policies")
    default_policy: str = "legal-default"
    max_chars: int = 200_000
    max_upload_bytes: int = 25 * 1024 * 1024
    enable_ner: bool = True

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        api_keys = _split(env.get("CATO_API_KEYS"))
        admin_keys = _split(env.get("CATO_ADMIN_KEYS"))
        if not api_keys:
            raise SettingsError("CATO_API_KEYS must contain at least one key")
        for k in api_keys + admin_keys:
            if len(k) < 24:
                raise SettingsError("API keys must be at least 24 characters")
        if set(api_keys) & set(admin_keys):
            raise SettingsError("admin keys must differ from API keys")
        return cls(
            api_key_hashes={_hash(k) for k in api_keys},
            admin_key_hashes={_hash(k) for k in admin_keys},
            vault_key=env.get("CATO_VAULT_KEY") or None,
            vault_path=Path(env.get("CATO_VAULT_PATH", "data/vault.json")),
            policy_dir=Path(env.get("CATO_POLICY_DIR", "data/policies")),
            default_policy=env.get("CATO_DEFAULT_POLICY", "legal-default"),
            max_chars=int(env.get("CATO_MAX_CHARS", "200000")),
            max_upload_bytes=int(env.get("CATO_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
            enable_ner=env.get("CATO_ENABLE_NER", "1") != "0",
        )

    def is_api_key(self, key: str) -> bool:
        return _contains(self.api_key_hashes, key) or self.is_admin_key(key)

    def is_admin_key(self, key: str) -> bool:
        return _contains(self.admin_key_hashes, key)


def _contains(hashes: set[str], key: str) -> bool:
    candidate = _hash(key)
    found = False
    for h in hashes:  # constant-time comparison against every entry
        found |= hmac.compare_digest(h, candidate)
    return found
