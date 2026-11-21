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


# Settings handed to the MCP server; everything else stays out of ``env``.
_PASS_THROUGH = ("ANONYMIZER_MCP",)


class SettingsError(RuntimeError):
    pass


@dataclass
class Settings:
    """
    ANONYMIZER_API_KEYS        comma-separated keys for scan/classify/anonymize/protect (optional; keys can
                         also be created in the dashboard. Environment keys belong to the default org)
    ANONYMIZER_ADMIN_KEYS      comma-separated keys for restore and policy management (optional;
                         without admin keys those endpoints are disabled)
    ANONYMIZER_ACCOUNTS_DB     SQLite file for organizations, users, sessions, API keys (default data/accounts.db)
    ANONYMIZER_AUDIT_DB        SQLite file for the audit log (default data/audit.db)
    ANONYMIZER_SESSION_HOURS   dashboard session lifetime (default 12)
    ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL / _PASSWORD  creates the first admin if no user exists yet
    ANONYMIZER_VAULT_KEY       base64 32-byte vault key (optional; enables reversible pseudonyms)
    ANONYMIZER_VAULT_PATH      vault file (default ./data/vault.json)
    ANONYMIZER_POLICY_DIR      policy store directory (default ./data/policies)
    ANONYMIZER_DEFAULT_POLICY  policy name used when a request names none and no scope applies
    ANONYMIZER_MAX_CHARS       max characters per text (default 200000)
    ANONYMIZER_MAX_UPLOAD_BYTES max document upload size (default 25 MiB)
    ANONYMIZER_ENABLE_NER      "0" to disable spaCy NER (not recommended)
    ANONYMIZER_PLAYGROUND_DB  SQLite file for uploaded playground CSV datasets (default data/playground.db)
    ANONYMIZER_PLAYGROUND_POLICY  policy for playground queries (default support-default; the former
                               ANONYMIZER_CONVERSATIONS_POLICY is still read as a fallback)
    ANONYMIZER_FEEDBACK_DB    SQLite file for corrections from the Chat tab, raw text (default data/feedback.db)
    ANONYMIZER_TRACE_DB        SQLite file for metadata-only traces (default data/traces.db)
    ANONYMIZER_TRACE_RETENTION_DAYS  default 30
    ANONYMIZER_TRACE_CONTENT   "1" also stores protected text and original values per trace
                               (clear-text personal data, admins only; test data only)
    ANONYMIZER_KEEP_TERMS      comma-separated own brands/products kept unchanged by NER (e.g. "ACME")
    ANONYMIZER_NER_MODEL_DE    German spaCy model; "de_core_news_lg+models/de_custom_ner/ner" uses the fine-tuned
                               support NER (base model plus NER weights)
    ANONYMIZER_CUSTOM_PATTERNS YAML file with deployment-specific patterns (order numbers, customer ids, ...)
    ANONYMIZER_MCP_HTTP        "1" serves the MCP server over HTTP at /mcp (bearer: a OpenAnonymizer API key)
    """

    api_key_hashes: set[str]
    admin_key_hashes: set[str] = field(default_factory=set)
    vault_key: str | None = None
    vault_path: Path = Path("data/vault.json")
    policy_dir: Path = Path("data/policies")
    default_policy: str = "banking-default"
    max_chars: int = 200_000
    max_upload_bytes: int = 25 * 1024 * 1024
    enable_ner: bool = True
    trace_db: str = "data/traces.db"
    trace_retention_days: int = 30
    trace_content: bool = False
    accounts_db: str = "data/accounts.db"
    audit_db: str = "data/audit.db"
    session_hours: float = 12
    custom_patterns: str | None = None
    keep_terms: list[str] = field(default_factory=list)
    playground_db: str = "data/playground.db"
    feedback_db: str = "data/feedback.db"
    playground_policy: str = "support-default"
    mcp_http: bool = False
    bootstrap_admin: tuple[str, str] | None = field(default=None, repr=False)
    env: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        api_keys = _split(env.get("ANONYMIZER_API_KEYS"))
        admin_keys = _split(env.get("ANONYMIZER_ADMIN_KEYS"))
        for k in api_keys + admin_keys:
            if len(k) < 24:
                raise SettingsError("API keys must be at least 24 characters")
        if set(api_keys) & set(admin_keys):
            raise SettingsError("admin keys must differ from API keys")
        return cls(
            api_key_hashes={_hash(k) for k in api_keys},
            admin_key_hashes={_hash(k) for k in admin_keys},
            vault_key=env.get("ANONYMIZER_VAULT_KEY") or None,
            vault_path=Path(env.get("ANONYMIZER_VAULT_PATH", "data/vault.json")),
            policy_dir=Path(env.get("ANONYMIZER_POLICY_DIR", "data/policies")),
            default_policy=env.get("ANONYMIZER_DEFAULT_POLICY", "banking-default"),
            max_chars=int(env.get("ANONYMIZER_MAX_CHARS", "200000")),
            max_upload_bytes=int(env.get("ANONYMIZER_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
            enable_ner=env.get("ANONYMIZER_ENABLE_NER", "1") != "0",
            trace_db=env.get("ANONYMIZER_TRACE_DB", "data/traces.db"),
            trace_retention_days=int(env.get("ANONYMIZER_TRACE_RETENTION_DAYS", "30")),
            trace_content=env.get("ANONYMIZER_TRACE_CONTENT", "0") == "1",
            accounts_db=env.get("ANONYMIZER_ACCOUNTS_DB", "data/accounts.db"),
            audit_db=env.get("ANONYMIZER_AUDIT_DB", "data/audit.db"),
            session_hours=float(env.get("ANONYMIZER_SESSION_HOURS", "12")),
            custom_patterns=env.get("ANONYMIZER_CUSTOM_PATTERNS") or None,
            keep_terms=_split(env.get("ANONYMIZER_KEEP_TERMS")),
            playground_db=env.get("ANONYMIZER_PLAYGROUND_DB", "data/playground.db"),
            feedback_db=env.get("ANONYMIZER_FEEDBACK_DB", "data/feedback.db"),
            playground_policy=(env.get("ANONYMIZER_PLAYGROUND_POLICY") or env.get("ANONYMIZER_CONVERSATIONS_POLICY")
                               or "support-default"),
            mcp_http=env.get("ANONYMIZER_MCP_HTTP", "0") == "1",
            bootstrap_admin=_bootstrap(env),
            env={k: v for k, v in env.items() if k.startswith(_PASS_THROUGH)},
        )

    def is_api_key(self, key: str) -> bool:
        return _contains(self.api_key_hashes, key) or self.is_admin_key(key)

    def is_admin_key(self, key: str) -> bool:
        return _contains(self.admin_key_hashes, key)


def _bootstrap(env: dict[str, str]) -> tuple[str, str] | None:
    email, password = env.get("ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL"), env.get("ANONYMIZER_BOOTSTRAP_ADMIN_PASSWORD")
    if bool(email) != bool(password):
        raise SettingsError("set both ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL and ANONYMIZER_BOOTSTRAP_ADMIN_PASSWORD")
    return (email, password) if email and password else None


def _contains(hashes: set[str], key: str) -> bool:
    candidate = _hash(key)
    found = False
    for h in hashes:  # constant-time comparison against every entry
        found |= hmac.compare_digest(h, candidate)
    return found
