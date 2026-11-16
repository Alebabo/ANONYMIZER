"""API settings from environment variables. Fails closed: invalid keys, no start; no keys, no access."""

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


# Settings handed to the gateway, sources, prompt store and MCP; everything else stays out of ``env``.
_PASS_THROUGH = ("CATO_UPSTREAM", "CATO_LOCAL", "CATO_GATEWAY", "CATO_SOURCE", "CATO_CONVERSATIONS",
                 "CATO_PROMPTS", "CATO_MCP")


class SettingsError(RuntimeError):
    pass


@dataclass
class Settings:
    """
    CATO_API_KEYS        comma-separated keys for scan/classify/anonymize/protect (optional; keys can
                         also be created in the dashboard. Environment keys belong to the default org)
    CATO_ADMIN_KEYS      comma-separated keys for restore and policy management (optional;
                         without admin keys those endpoints are disabled)
    CATO_ACCOUNTS_DB     SQLite file for organizations, users, sessions, API keys (default data/accounts.db)
    CATO_AUDIT_DB        SQLite file for the audit log (default data/audit.db)
    CATO_SESSION_HOURS   dashboard session lifetime (default 12)
    CATO_BOOTSTRAP_ADMIN_EMAIL / _PASSWORD  creates the first admin if no user exists yet
    CATO_VAULT_KEY       base64 32-byte vault key (optional; enables reversible pseudonyms)
    CATO_VAULT_PATH      vault file (default ./data/vault.json)
    CATO_POLICY_DIR      policy store directory (default ./data/policies)
    CATO_DEFAULT_POLICY  policy name used when a request names none and no scope applies
    CATO_MAX_CHARS       max characters per text (default 200000)
    CATO_MAX_UPLOAD_BYTES max document upload size (default 25 MiB)
    CATO_ENABLE_NER      "0" to disable spaCy NER (not recommended)
    CATO_TRACE_DB        SQLite file for metadata-only traces (default data/traces.db)
    CATO_TRACE_RETENTION_DAYS  default 30
    CATO_UPSTREAM_URL / _KEY / _PROVIDER            external OpenAI-compatible provider
    CATO_LOCAL_UPSTREAM_URL / _KEY / CATO_LOCAL_MODEL  optional local model for local_only content
    CATO_GATEWAY_RESTORE "0" to return placeholders instead of restored values
    CATO_CUSTOM_PATTERNS YAML file with deployment-specific patterns (order numbers, customer ids, ...)
    CATO_SOURCE / CATO_SOURCE_*         conversation source (jsonl | http | langfuse), see docs/conversations.md
    CATO_CONVERSATIONS_*                policy, quota, k, database, label allow-list for conversation access
    CATO_PROMPTS / CATO_PROMPTS_*       prompt store (local | langfuse), see docs/prompts.md
    CATO_MCP_HTTP        "1" serves the MCP server over HTTP at /mcp (bearer: a Cato API key)
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
    trace_db: str = "data/traces.db"
    trace_retention_days: int = 30
    accounts_db: str = "data/accounts.db"
    audit_db: str = "data/audit.db"
    session_hours: float = 12
    custom_patterns: str | None = None
    conversations_db: str = "data/conversations.db"
    mcp_http: bool = False
    bootstrap_admin: tuple[str, str] | None = field(default=None, repr=False)
    env: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        api_keys = _split(env.get("CATO_API_KEYS"))
        admin_keys = _split(env.get("CATO_ADMIN_KEYS"))
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
            trace_db=env.get("CATO_TRACE_DB", "data/traces.db"),
            trace_retention_days=int(env.get("CATO_TRACE_RETENTION_DAYS", "30")),
            accounts_db=env.get("CATO_ACCOUNTS_DB", "data/accounts.db"),
            audit_db=env.get("CATO_AUDIT_DB", "data/audit.db"),
            session_hours=float(env.get("CATO_SESSION_HOURS", "12")),
            custom_patterns=env.get("CATO_CUSTOM_PATTERNS") or None,
            conversations_db=env.get("CATO_CONVERSATIONS_DB", "data/conversations.db"),
            mcp_http=env.get("CATO_MCP_HTTP", "0") == "1",
            bootstrap_admin=_bootstrap(env),
            env={k: v for k, v in env.items() if k.startswith(_PASS_THROUGH)},
        )

    def is_api_key(self, key: str) -> bool:
        return _contains(self.api_key_hashes, key) or self.is_admin_key(key)

    def is_admin_key(self, key: str) -> bool:
        return _contains(self.admin_key_hashes, key)


def _bootstrap(env: dict[str, str]) -> tuple[str, str] | None:
    email, password = env.get("CATO_BOOTSTRAP_ADMIN_EMAIL"), env.get("CATO_BOOTSTRAP_ADMIN_PASSWORD")
    if bool(email) != bool(password):
        raise SettingsError("set both CATO_BOOTSTRAP_ADMIN_EMAIL and CATO_BOOTSTRAP_ADMIN_PASSWORD")
    return (email, password) if email and password else None


def _contains(hashes: set[str], key: str) -> bool:
    candidate = _hash(key)
    found = False
    for h in hashes:  # constant-time comparison against every entry
        found |= hmac.compare_digest(h, candidate)
    return found
