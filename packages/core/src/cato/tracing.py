"""Privacy traces: one record per processed request, metadata only.

A trace contains entity types and counts, risk, policy name/version/hash,
outcome, actions, provider, model, latency and errors. It never contains
the submitted text, detected values, placeholders or vault data, so the
trace store itself does not become a privacy risk.

Storage: SQLite (stdlib). Retention is enforced on write
(``retention_days``). PostgreSQL/ClickHouse can replace it later behind
the same interface.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    name: str
    detail: str
    status: str = "ok"  # ok | warning | blocked | error


class Trace(BaseModel):
    id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    created_at: float = Field(default_factory=time.time)
    route: str
    outcome: str | None = None
    allowed: bool | None = None
    risk: str | None = None
    needs_review: bool = False
    policy: str | None = None
    policy_hash: str | None = None
    destination: str | None = None
    provider: str | None = None
    model: str | None = None
    language: str | None = None
    latency_ms: float | None = None
    status: int = 200
    error: str | None = None
    entity_counts: dict[str, int] = Field(default_factory=dict)
    risk_counts: dict[str, int] = Field(default_factory=dict)
    actions: dict[str, int] = Field(default_factory=dict)  # "type:action" -> n
    transformations: int = 0
    signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)
    # MCP proxy: which upstream tool produced the data, and where in the result entities were found
    # (JSON paths with array indices collapsed, e.g. "$.rows[].email" -> {"email": 12}). No values.
    upstream: str | None = None
    tool: str | None = None
    mode: str | None = None  # enforce | observe
    fields: dict[str, dict[str, int]] = Field(default_factory=dict)


def trace_from_protect(route: str, result: Any, latency_ms: float | None = None, **extra: Any) -> Trace:
    """Build a trace from a :class:`cato.pipeline.ProtectResult`."""
    c, d = result.classification, result.decision
    entity_counts = dict(Counter(e.entity_type for e in c.entities))
    risk_counts = {k.value: v for k, v in c.counts.items() if v}
    actions = dict(Counter(f"{e.entity_type}:{e.action.value}" for e in d.entities))
    n_trans = len(result.anonymization.transformations) if result.anonymization else 0
    crit = sum(v for k, v in c.counts.items() if k.value == "critical")
    sens = sum(v for k, v in c.counts.items() if k.value == "sensitive")
    steps = [
        TraceStep(name="Request received", detail=f"{route}"),
        TraceStep(name="Privacy detection", detail=f"{len(c.entities)} entities detected",
                  status="warning" if c.warnings else "ok"),
        TraceStep(name="Classification", detail=f"{crit} critical · {sens} sensitive · risk {c.risk.value}",
                  status="warning" if c.needs_review else "ok"),
        TraceStep(name="Policy evaluation", detail=f"{d.policy} → {d.outcome.value}",
                  status="ok" if d.outcome.value == "allow" else "blocked"),
    ]
    if result.anonymization is not None:
        steps.append(TraceStep(name="Anonymization", detail=f"{n_trans} transformations applied"))
    return Trace(
        route=route, outcome=d.outcome.value, allowed=result.allowed, risk=c.risk.value,
        needs_review=c.needs_review, policy=d.policy, policy_hash=d.policy_hash, destination=d.destination,
        language=c.language, latency_ms=latency_ms, entity_counts=entity_counts, risk_counts=risk_counts,
        actions=actions, transformations=n_trans, signals=c.signals, warnings=c.warnings, steps=steps, **extra,
    )


def merge_traces(route: str, parts: list[Trace], **extra: Any) -> Trace:
    """Combine per-message traces (gateway) into one request trace."""
    order = ["allow", "review", "local_only", "block"]
    risks = ["low", "sensitive", "critical"]
    outcome = max((p.outcome for p in parts if p.outcome), key=order.index, default="allow")
    risk = max((p.risk for p in parts if p.risk), key=risks.index, default="low")
    def add(attr: str) -> dict[str, int]:
        total: Counter = Counter()
        for p in parts:
            total.update(getattr(p, attr))
        return dict(total)
    first = next((p for p in parts if p.policy), None)
    return Trace(
        route=route, outcome=outcome, allowed=outcome == "allow", risk=risk,
        needs_review=any(p.needs_review for p in parts), policy=first.policy if first else None,
        policy_hash=first.policy_hash if first else None, destination=first.destination if first else None,
        entity_counts=add("entity_counts"), risk_counts=add("risk_counts"), actions=add("actions"),
        transformations=sum(p.transformations for p in parts),
        signals=sorted({s for p in parts for s in p.signals}), warnings=sorted({w for p in parts for w in p.warnings}),
        **extra,
    )


DEFAULT_ORG = "default"


class TraceStore:
    """Traces are stored per organization (``org_id``); every read is scoped to one.

    ``retention_for`` maps an organization to its retention in days (falls back
    to ``retention_days``).
    """

    def __init__(self, path: str | Path = ":memory:", retention_days: int = 30,
                 retention_for: Callable[[str], int | None] | None = None) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.retention_for = retention_for
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS traces (
            id TEXT PRIMARY KEY, created_at REAL NOT NULL, route TEXT, outcome TEXT, risk TEXT,
            provider TEXT, status INTEGER, data TEXT NOT NULL)""")
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(traces)")}
        if "org_id" not in cols:  # migration: traces written before accounts belong to the default org
            self._db.execute(f"ALTER TABLE traces ADD COLUMN org_id TEXT NOT NULL DEFAULT '{DEFAULT_ORG}'")
        self._db.execute("CREATE INDEX IF NOT EXISTS traces_created ON traces(created_at)")
        self._db.execute("CREATE INDEX IF NOT EXISTS traces_org_created ON traces(org_id, created_at)")
        self._db.commit()
        self._writes = 0

    def add(self, trace: Trace, org_id: str = DEFAULT_ORG) -> Trace:
        with self._lock:
            self._db.execute(
                "INSERT INTO traces (id, created_at, route, outcome, risk, provider, status, data, org_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (trace.id, trace.created_at, trace.route, trace.outcome, trace.risk, trace.provider, trace.status,
                 trace.model_dump_json(), org_id),
            )
            self._writes += 1
            if self._writes % 100 == 1:
                self._purge()
            self._db.commit()
        return trace

    def _purge(self) -> None:
        now = time.time()
        for (org,) in self._db.execute("SELECT DISTINCT org_id FROM traces").fetchall():
            days = (self.retention_for(org) if self.retention_for else None) or self.retention_days
            self._db.execute("DELETE FROM traces WHERE org_id = ? AND created_at < ?", (org, now - days * 86400))

    def purge(self) -> None:
        with self._lock:
            self._purge()
            self._db.commit()

    def get(self, trace_id: str, org_id: str = DEFAULT_ORG) -> Trace | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM traces WHERE id = ? AND org_id = ?",
                                   (trace_id, org_id)).fetchone()
        return Trace.model_validate_json(row[0]) if row else None

    def list(self, limit: int = 50, outcome: str | None = None, route: str | None = None,
             since: float | None = None, org_id: str = DEFAULT_ORG) -> list[Trace]:
        sql, args = "SELECT data FROM traces WHERE org_id = ?", [org_id]
        if outcome:
            sql += " AND outcome = ?"
            args.append(outcome)
        if route:
            sql += " AND route = ?"
            args.append(route)
        if since:
            sql += " AND created_at >= ?"
            args.append(since)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(min(max(limit, 1), 500))
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [Trace.model_validate_json(r[0]) for r in rows]

    def metrics(self, hours: int = 24, org_id: str = DEFAULT_ORG) -> dict[str, Any]:
        since = time.time() - hours * 3600
        traces = self._all_since(since, org_id)
        total = len(traces)
        with_det = sum(1 for t in traces if t.entity_counts)
        detections = sum(sum(t.entity_counts.values()) for t in traces)
        not_allowed = [t for t in traces if t.outcome and t.outcome != "allow"]
        latencies = sorted(t.latency_ms for t in traces if t.latency_ms is not None)
        entity_dist: Counter = Counter()
        actions: Counter = Counter()
        for t in traces:
            entity_dist.update(t.entity_counts)
            actions.update({k.split(":", 1)[1]: v for k, v in t.actions.items()})
        anonymized = sum(v for k, v in actions.items() if k not in ("allow", "block", "local_only", "review"))
        buckets: Counter = Counter()
        for t in traces:
            buckets[int(t.created_at // 3600 * 3600)] += 1
        start = int(since // 3600 * 3600)
        series = [{"t": h, "requests": buckets.get(h, 0)} for h in range(start, int(time.time()) + 1, 3600)]
        return {
            "window_hours": hours,
            "requests": total,
            "requests_with_detections": with_det,
            "detection_rate": round(with_det / total, 4) if total else 0.0,
            "detections": detections,
            "anonymized_entities": anonymized,
            "anonymization_rate": round(anonymized / detections, 4) if detections else 0.0,
            "not_allowed": len(not_allowed),
            "block_rate": round(len(not_allowed) / total, 4) if total else 0.0,
            "by_outcome": dict(Counter(t.outcome or "n/a" for t in traces)),
            "by_risk": dict(Counter(t.risk or "n/a" for t in traces)),
            "by_route": dict(Counter(t.route for t in traces)),
            "by_provider": dict(Counter(t.provider for t in traces if t.provider)),
            "by_policy": dict(Counter(t.policy for t in traces if t.policy)),
            "entity_distribution": dict(entity_dist.most_common()),
            "actions": dict(actions),
            "latency_ms": {
                "avg": round(sum(latencies) / len(latencies), 1) if latencies else None,
                "p95": latencies[int(len(latencies) * 0.95) - 1] if len(latencies) >= 20 else (latencies[-1] if latencies else None),
            },
            "errors": sum(1 for t in traces if t.status >= 500),
            "timeseries": series,
        }

    def _all_since(self, since: float, org_id: str) -> list[Trace]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM traces WHERE org_id = ? AND created_at >= ? ORDER BY created_at",
                                    (org_id, since)).fetchall()
        return [Trace.model_validate_json(r[0]) for r in rows]
