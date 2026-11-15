"""Accounts: organizations, users, sessions and API keys (SQLite, stdlib only).

Security properties:
* Passwords are hashed with scrypt (N=2^14, r=8, p=1) and a random salt.
* Session tokens and API keys are random (256 bit) and stored as SHA-256
  hashes only. The plaintext is returned exactly once, on creation.
* Unknown e-mail and wrong password take the same code path (a dummy scrypt
  runs for unknown users), so login timing does not reveal accounts.
* Every query is scoped by organization id; there is no cross-org listing.

Data model (one row per entity, ids are short random strings):
  organizations(id, name, created_at, trace_retention_days)
  users(id, org_id, email, name, role, password_hash, created_at, last_login_at, disabled)
  sessions(token_hash, user_id, created_at, expires_at)
  api_keys(id, org_id, name, prefix, key_hash, role, created_by, created_at, last_used_at, revoked_at)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

DEFAULT_ORG = "default"
UserRole = Literal["admin", "member"]
KeyRole = Literal["user", "admin"]
MIN_PASSWORD = 12
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


class AccountError(ValueError):
    """Invalid input or forbidden state change; the message is safe to show."""


# -- hashing -------------------------------------------------------------------

def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"password must be at least {MIN_PASSWORD} characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${dk}".format(
        **_SCRYPT, salt=base64.b64encode(salt).decode(), dk=base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32,
                                   n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, base64.b64decode(dk))


_DUMMY_HASH = hash_password("dummy-password-for-timing")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


# -- principal -----------------------------------------------------------------

@dataclass(frozen=True)
class Principal:
    """Who is calling. ``kind`` is env_key | api_key | session."""

    kind: str
    org_id: str
    role: str  # user/admin for keys, admin/member for sessions
    id: str  # user id or key id ("env" for environment keys)
    label: str  # e-mail or key name/prefix, for the audit log

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def actor_type(self) -> str:
        return "user" if self.kind == "session" else "api_key"


# -- store ---------------------------------------------------------------------

class AccountStore:
    def __init__(self, path: str | Path = ":memory:", session_hours: float = 12) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.session_seconds = int(session_hours * 3600)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL,
                trace_retention_days INTEGER);  -- NULL: server default (CATO_TRACE_RETENTION_DAYS)
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES organizations(id),
                email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL,
                password_hash TEXT NOT NULL, created_at REAL NOT NULL, last_login_at REAL,
                disabled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                created_at REAL NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES organizations(id),
                name TEXT NOT NULL, prefix TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL, created_by TEXT, created_at REAL NOT NULL,
                last_used_at REAL, revoked_at REAL);
        """)
        self._db.commit()
        self.ensure_org(DEFAULT_ORG, "Default")

    # -- organizations ---------------------------------------------------------
    def ensure_org(self, org_id: str, name: str) -> dict[str, Any]:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO organizations (id, name, created_at) VALUES (?,?,?)",
                             (org_id, name, time.time()))
            self._db.commit()
        return self.get_org(org_id)

    def create_org(self, name: str, org_id: str | None = None) -> dict[str, Any]:
        name = _clean_name(name)
        org_id = org_id or _id("org")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", org_id):
            raise AccountError("organization id: 2-41 chars, lowercase letters, digits, '-' or '_'")
        with self._lock:
            try:
                self._db.execute("INSERT INTO organizations (id, name, created_at) VALUES (?,?,?)",
                                 (org_id, name, time.time()))
                self._db.commit()
            except sqlite3.IntegrityError:
                raise AccountError("organization already exists") from None
        return self.get_org(org_id)

    def get_org(self, org_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        if row is None:
            raise AccountError("organization not found")
        return dict(row)

    def list_orgs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM organizations ORDER BY created_at")]

    def update_org(self, org_id: str, name: str | None = None,
                   trace_retention_days: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        before = self.get_org(org_id)
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = _clean_name(name)
        if trace_retention_days is not None:
            if not 1 <= trace_retention_days <= 3650:
                raise AccountError("retention must be between 1 and 3650 days")
            fields["trace_retention_days"] = trace_retention_days
        if fields:
            with self._lock:
                self._db.execute(f"UPDATE organizations SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                                 (*fields.values(), org_id))
                self._db.commit()
        return before, self.get_org(org_id)

    # -- users -----------------------------------------------------------------
    def create_user(self, org_id: str, email: str, name: str, password: str,
                    role: UserRole = "member") -> dict[str, Any]:
        email = email.strip().lower()
        if not _EMAIL.match(email):
            raise AccountError("invalid e-mail address")
        if role not in ("admin", "member"):
            raise AccountError("role must be admin or member")
        self.get_org(org_id)
        pw = hash_password(password)
        uid = _id("usr")
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO users (id, org_id, email, name, role, password_hash, created_at) VALUES (?,?,?,?,?,?,?)",
                    (uid, org_id, email, _clean_name(name), role, pw, time.time()))
                self._db.commit()
            except sqlite3.IntegrityError:
                raise AccountError("a user with this e-mail already exists") from None
        return self.get_user(org_id, uid)

    def get_user(self, org_id: str, user_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM users WHERE id = ? AND org_id = ?", (user_id, org_id)).fetchone()
        if row is None:
            raise AccountError("user not found")
        return _public_user(row)

    def list_users(self, org_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM users WHERE org_id = ? ORDER BY created_at", (org_id,)).fetchall()
        return [_public_user(r) for r in rows]

    def count_users(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def update_user(self, org_id: str, user_id: str, actor_id: str, role: str | None = None,
                    disabled: bool | None = None, name: str | None = None) -> tuple[dict, dict]:
        before = self.get_user(org_id, user_id)
        if role is not None and role not in ("admin", "member"):
            raise AccountError("role must be admin or member")
        losing_admin = before["role"] == "admin" and not before["disabled"] and (
            (role is not None and role != "admin") or disabled)
        if losing_admin:
            if user_id == actor_id:
                raise AccountError("you cannot remove your own admin access")
            if self._active_admins(org_id) <= 1:
                raise AccountError("an organization needs at least one active admin")
        fields: dict[str, Any] = {}
        if role is not None:
            fields["role"] = role
        if disabled is not None:
            fields["disabled"] = int(disabled)
        if name is not None:
            fields["name"] = _clean_name(name)
        if fields:
            with self._lock:
                self._db.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ? AND org_id = ?",
                                 (*fields.values(), user_id, org_id))
                if disabled:
                    self._db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                self._db.commit()
        return before, self.get_user(org_id, user_id)

    def set_password(self, org_id: str, user_id: str, current: str, new: str) -> None:
        with self._lock:
            row = self._db.execute("SELECT password_hash FROM users WHERE id = ? AND org_id = ?",
                                   (user_id, org_id)).fetchone()
        if row is None or not verify_password(current, row["password_hash"]):
            raise AccountError("current password is wrong")
        pw = hash_password(new)
        with self._lock:
            self._db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw, user_id))
            self._db.commit()

    def _active_admins(self, org_id: str) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM users WHERE org_id = ? AND role = 'admin' AND disabled = 0",
                                    (org_id,)).fetchone()[0]

    # -- sessions --------------------------------------------------------------
    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        """Returns the user row if the credentials are valid and the user is active."""
        with self._lock:
            row = self._db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
        if not row or not ok or row["disabled"]:
            return None
        return _public_user(row)

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return _public_user(row) if row else None

    def create_session(self, user_id: str) -> tuple[str, float]:
        token = "cses_" + secrets.token_urlsafe(32)
        now = time.time()
        expires = now + self.session_seconds
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            self._db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (token_hash(token), user_id, now, expires))
            self._db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))
            self._db.commit()
        return token, expires

    def revoke_session(self, token: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
            self._db.commit()

    def revoke_user_sessions(self, user_id: str, keep: str | None = None) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                             (user_id, token_hash(keep) if keep else ""))
            self._db.commit()

    # -- api keys --------------------------------------------------------------
    def create_api_key(self, org_id: str, name: str, role: KeyRole, created_by: str | None) -> tuple[str, dict]:
        if role not in ("user", "admin"):
            raise AccountError("role must be user or admin")
        self.get_org(org_id)
        key = "cato_" + secrets.token_urlsafe(32)
        kid = _id("key")
        with self._lock:
            self._db.execute(
                "INSERT INTO api_keys (id, org_id, name, prefix, key_hash, role, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (kid, org_id, _clean_name(name), key[:12], token_hash(key), role, created_by, time.time()))
            self._db.commit()
        return key, self.get_api_key(org_id, kid)

    def get_api_key(self, org_id: str, key_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM api_keys WHERE id = ? AND org_id = ?", (key_id, org_id)).fetchone()
        if row is None:
            raise AccountError("API key not found")
        return _public_key(row)

    def list_api_keys(self, org_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM api_keys WHERE org_id = ? ORDER BY created_at DESC",
                                    (org_id,)).fetchall()
        return [_public_key(r) for r in rows]

    def revoke_api_key(self, org_id: str, key_id: str) -> tuple[dict, dict]:
        before = self.get_api_key(org_id, key_id)
        if before["revoked_at"]:
            raise AccountError("API key is already revoked")
        with self._lock:
            self._db.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND org_id = ?",
                             (time.time(), key_id, org_id))
            self._db.commit()
        return before, self.get_api_key(org_id, key_id)

    def has_admin_keys(self) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM api_keys WHERE role = 'admin' AND revoked_at IS NULL"
                                    ).fetchone() is not None

    # -- resolution ------------------------------------------------------------
    def principal(self, token: str) -> Principal | None:
        h, now = token_hash(token), time.time()
        if token.startswith("cses_"):
            with self._lock:
                row = self._db.execute(
                    "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                    "WHERE s.token_hash = ? AND s.expires_at > ? AND u.disabled = 0", (h, now)).fetchone()
            return Principal("session", row["org_id"], row["role"], row["id"], row["email"]) if row else None
        with self._lock:
            row = self._db.execute("SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", (h,)).fetchone()
            if row is None:
                return None
            if not row["last_used_at"] or now - row["last_used_at"] > 60:  # throttle writes
                self._db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
                self._db.commit()
        return Principal("api_key", row["org_id"], row["role"], row["id"], f"{row['name']} ({row['prefix']}…)")


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not 1 <= len(name) <= 100:
        raise AccountError("name must be 1-100 characters")
    return name


def _public_user(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("password_hash", None)
    d["disabled"] = bool(d["disabled"])
    return d


def _public_key(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("key_hash", None)
    return d


__all__ = ["AccountError", "AccountStore", "DEFAULT_ORG", "MIN_PASSWORD", "Principal", "hash_password",
           "verify_password"]
