"""Audit log: who did what, when, to which resource.

The record shape follows Langfuse's audit log (MIT,
``web/src/features/audit-logs/auditLog.ts``): resource type and id, action,
``before``/``after`` snapshots and an actor that is a user, an API key or
the system.

Additions for OpenAnonymizer:
* Append-only. The store has no update or delete method.
* Tamper evidence: each entry carries ``hash = sha256(prev_hash + entry)``,
  chained per organization. :meth:`AuditLog.verify` recomputes the chain and
  reports the first broken entry.
* No secrets or content: snapshots are filtered through a deny list
  (password hashes, key hashes, tokens, text). Restore events record the
  number of resolved placeholders, never the values.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from anonymizer.accounts import Principal

GENESIS = "0" * 64
_DENY = {"password", "password_hash", "key_hash", "token", "token_hash", "key", "text", "value", "values"}


def _clean(snapshot: Any) -> Any:
    if isinstance(snapshot, dict):
        return {k: _clean(v) for k, v in snapshot.items() if k not in _DENY}
    if isinstance(snapshot, list):
        return [_clean(v) for v in snapshot]
    return snapshot


def _digest(prev: str, entry: dict[str, Any]) -> str:
    fields = {k: entry[k] for k in ("id", "created_at", "org_id", "actor_type", "actor_id", "actor_label",
                                    "resource_type", "resource_id", "action", "before", "after")}
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev + payload).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
                org_id TEXT NOT NULL, actor_type TEXT NOT NULL, actor_id TEXT, actor_label TEXT,
                resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, action TEXT NOT NULL,
                before TEXT, after TEXT, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS audit_org_seq ON audit_logs(org_id, seq);
        """)
        self._db.commit()

    def record(self, org_id: str, action: str, resource_type: str, resource_id: str,
               actor: Principal | None = None, before: Any = None, after: Any = None,
               actor_label: str | None = None, actor_type: str | None = None) -> dict[str, Any]:
        """Append one entry. ``actor=None`` means the system (CLI, bootstrap) unless ``actor_type``
        says otherwise (``anonymous`` for unauthenticated attempts such as failed logins)."""
        entry = {
            "id": f"aud_{secrets.token_hex(8)}",
            "created_at": round(time.time(), 3),
            "org_id": org_id,
            "actor_type": actor.actor_type if actor else (actor_type or "system"),
            "actor_id": actor.id if actor else None,
            "actor_label": actor_label or (actor.label if actor else "system"),
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
            "before": json.dumps(_clean(before), sort_keys=True, default=str) if before is not None else None,
            "after": json.dumps(_clean(after), sort_keys=True, default=str) if after is not None else None,
        }
        with self._lock:
            row = self._db.execute("SELECT hash FROM audit_logs WHERE org_id = ? ORDER BY seq DESC LIMIT 1",
                                   (org_id,)).fetchone()
            entry["prev_hash"] = row["hash"] if row else GENESIS
            entry["hash"] = _digest(entry["prev_hash"], entry)
            cols = ", ".join(entry)
            self._db.execute(f"INSERT INTO audit_logs ({cols}) VALUES ({', '.join('?' * len(entry))})",
                             tuple(entry.values()))
            self._db.commit()
        return _out(entry)

    def list(self, org_id: str, limit: int = 50, before_seq: int | None = None, action: str | None = None,
             resource_type: str | None = None, actor_id: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM audit_logs WHERE org_id = ?", [org_id]
        for col, val in (("action", action), ("resource_type", resource_type), ("actor_id", actor_id)):
            if val:
                sql += f" AND {col} = ?"
                args.append(val)
        if before_seq:
            sql += " AND seq < ?"
            args.append(before_seq)
        sql += " ORDER BY seq DESC LIMIT ?"
        args.append(min(max(limit, 1), 200))
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [_out(dict(r)) for r in rows]

    def get(self, org_id: str, entry_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM audit_logs WHERE org_id = ? AND id = ?",
                                   (org_id, entry_id)).fetchone()
        return _out(dict(row)) if row else None

    def facets(self, org_id: str) -> dict[str, list[str]]:
        with self._lock:
            actions = [r[0] for r in self._db.execute(
                "SELECT DISTINCT action FROM audit_logs WHERE org_id = ? ORDER BY action", (org_id,))]
            types = [r[0] for r in self._db.execute(
                "SELECT DISTINCT resource_type FROM audit_logs WHERE org_id = ? ORDER BY resource_type", (org_id,))]
        return {"actions": actions, "resource_types": types}

    def verify(self, org_id: str) -> dict[str, Any]:
        """Recompute the hash chain. ``ok`` is False at the first mismatch."""
        prev, count = GENESIS, 0
        with self._lock:
            rows = self._db.execute("SELECT * FROM audit_logs WHERE org_id = ? ORDER BY seq", (org_id,)).fetchall()
        for r in rows:
            e = dict(r)
            if e["prev_hash"] != prev or _digest(prev, e) != e["hash"]:
                return {"ok": False, "entries": count, "broken_at": e["id"]}
            prev, count = e["hash"], count + 1
        return {"ok": True, "entries": count, "broken_at": None, "head": prev}


def _out(e: dict[str, Any]) -> dict[str, Any]:
    out = dict(e)
    for k in ("before", "after"):
        out[k] = json.loads(out[k]) if out.get(k) else None
    return out


__all__ = ["AuditLog", "GENESIS"]
