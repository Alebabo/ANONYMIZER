"""Privacy traces: one record per processed request.

A trace contains entity types and counts, risk, policy name/version/hash,
outcome, actions, provider, model, latency and errors. By default it never
contains the submitted text, detected values, placeholders or vault data,
so the trace store itself does not become a privacy risk.

Opt-in content traces (``ANONYMIZER_TRACE_CONTENT=1``, test data only):
the store then also keeps what left OpenAnonymizer (the protected text) and
each replacement with its original value. The trace store then holds
personal data in clear text; only admins can read it.

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


class Replacement(BaseModel):
    type: str
    original: str
    replacement: str | None  # None: value withheld together with its text
    method: str | None = None


class ContentItem(BaseModel):
    """One protected text: where it came from, what was sent on and what was replaced."""
    label: str | None = None       # e.g. message role or JSON path
    input: str | None = None       # text as it reached OpenAnonymizer (original)
    output: str | None = None      # text as it left OpenAnonymizer; None if withheld
    withheld: bool = False
    replacements: list[Replacement] = Field(default_factory=list)


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
    # Structured results (playground): source and tool, and where in the result entities were found
    # (JSON paths with array indices collapsed, e.g. "$.rows[].email" -> {"email": 12}). No values.
    upstream: str | None = None
    tool: str | None = None
    mode: str | None = None  # enforce | observe
    fields: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Size of the call arguments and of the result handed to the model (characters of text; older MCP proxy traces).
    args_chars: int | None = None
    result_chars: int | None = None
    # What was read (e.g. playground dataset id). Content: only kept when the store allows it (see module doc).
    resource: str | None = None
    content: list[ContentItem] = Field(default_factory=list)
    # Who used the model and how: api | mcp | dashboard, and the key name or user e-mail (never a secret).
    client: str | None = None
    actor: str | None = None


def content_item(result: Any, original: str, label: str | None = None) -> ContentItem:
    """Output text and replacements (with original values) of one protected text."""
    reps: list[Replacement] = []
    if result.anonymization is not None:
        reps = [Replacement(type=t.entity_type, original=original[t.start:t.end], replacement=t.replacement,
                            method=t.method.value) for t in result.anonymization.transformations]
    else:
        reps = [Replacement(type=e.entity_type, original=original[e.start:e.end], replacement=None)
                for e in result.classification.entities]
    return ContentItem(label=label, input=original, output=result.text if result.allowed else None,
                       withheld=not result.allowed, replacements=reps)


def trace_from_scan(route: str, scan: Any, latency_ms: float | None = None, **extra: Any) -> Trace:
    """Trace for calls that only detect (scan, classify, anonymize without policy): counts, no values."""
    return Trace(
        route=route, language=scan.language, latency_ms=latency_ms, warnings=list(scan.warnings),
        entity_counts=dict(Counter(d.entity_type for d in scan.detections)), signals=sorted(scan.document_signals),
        steps=[TraceStep(name="Request received", detail=route),
               TraceStep(name="Privacy detection", detail=f"{len(scan.detections)} entities detected",
                         status="warning" if scan.warnings else "ok")],
        **extra,
    )


def trace_from_protect(route: str, result: Any, latency_ms: float | None = None, *, original: str | None = None,
                       label: str | None = None, **extra: Any) -> Trace:
    """Build a trace from a :class:`anonymizer.pipeline.ProtectResult`. With ``original`` the trace also
    carries the content item; :class:`TraceStore` drops it unless content traces are enabled."""
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
        actions=actions, transformations=n_trans, signals=c.signals, warnings=c.warnings, steps=steps,
        content=[content_item(result, original, label)] if original is not None else [], **extra,
    )


def merge_traces(route: str, parts: list[Trace], **extra: Any) -> Trace:
    """Combine per-part traces (e.g. the values of one playground query) into one request trace."""
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
        content=[c for p in parts for c in p.content], **extra,
    )


DEFAULT_ORG = "default"


def _pct(sorted_values: list[float], q: float) -> float | None:
    """Nearest-rank percentile; with fewer than 20 values the maximum (too few for a stable tail)."""
    if not sorted_values:
        return None
    if len(sorted_values) < 20 and q > 0.5:
        return round(sorted_values[-1], 1)
    return round(sorted_values[max(0, int(len(sorted_values) * q + 0.5) - 1)], 1)


class TraceStore:
    """Traces are stored per organization (``org_id``); every read is scoped to one.

    ``retention_for`` maps an organization to its retention in days (falls back
    to ``retention_days``). ``store_content`` keeps :attr:`Trace.content`; off by default.
    """

    def __init__(self, path: str | Path = ":memory:", retention_days: int = 30,
                 retention_for: Callable[[str], int | None] | None = None, store_content: bool = False) -> None:
        self.path = str(path)
        self.store_content = store_content
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
        if not self.store_content and trace.content:
            trace = trace.model_copy(update={"content": []})
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
             since: float | None = None, org_id: str = DEFAULT_ORG, client: str | None = None) -> list[Trace]:
        sql, args = "SELECT data FROM traces WHERE org_id = ?", [org_id]
        if client:
            sql += " AND json_extract(data, '$.client') = ?"
            args.append(client)
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
        now = time.time()
        since = now - hours * 3600
        traces = self._all_since(since, org_id)
        total = len(traces)
        with_det = sum(1 for t in traces if t.entity_counts)
        detections = sum(sum(t.entity_counts.values()) for t in traces)
        not_allowed = [t for t in traces if t.outcome and t.outcome != "allow"]
        latencies = sorted(t.latency_ms for t in traces if t.latency_ms is not None)
        entity_dist: Counter = Counter()
        actions: Counter = Counter()
        fields: Counter = Counter()
        for t in traces:
            entity_dist.update(t.entity_counts)
            actions.update({k.split(":", 1)[1]: v for k, v in t.actions.items()})
            for path, counts in t.fields.items():
                fields[path] += sum(counts.values())
        anonymized = sum(v for k, v in actions.items() if k not in ("allow", "block", "local_only", "review"))

        # Time series: hourly up to two days, daily beyond. Each bucket splits requests by what happened.
        step = 3600 if hours <= 48 else 86400
        buckets: dict[int, Counter] = {}
        for t in traces:
            b = buckets.setdefault(int(t.created_at // step * step), Counter())
            b["requests"] += 1
            if t.status >= 500:
                b["errors"] += 1
            elif t.outcome and t.outcome != "allow":
                b["not_allowed"] += 1
            elif t.entity_counts:
                b["anonymized"] += 1
            else:
                b["clean"] += 1
            b["entities"] += sum(t.entity_counts.values())
        start = int(since // step * step)
        keys = ("requests", "clean", "anonymized", "not_allowed", "errors", "entities")
        series = [{"t": h, **{k: buckets.get(h, Counter()).get(k, 0) for k in keys}}
                  for h in range(start, int(now) + 1, step)]

        # Per operation: upstream__tool (playground, older MCP proxy traces), else route.
        ops: dict[str, dict[str, Any]] = {}
        for t in traces:
            key = f"{t.upstream}__{t.tool}" if t.upstream and t.tool else t.route
            o = ops.setdefault(key, {"calls": 0, "entities": 0, "not_allowed": 0, "errors": 0, "observe": 0,
                                     "result_chars": 0, "_lat": []})
            o["calls"] += 1
            o["result_chars"] += t.result_chars or 0
            o["entities"] += sum(t.entity_counts.values())
            o["not_allowed"] += 1 if t.outcome and t.outcome != "allow" else 0
            o["errors"] += 1 if t.status >= 500 else 0
            o["observe"] += 1 if t.mode == "observe" else 0
            if t.latency_ms is not None:
                o["_lat"].append(t.latency_ms)
        by_operation = []
        for key, o in sorted(ops.items(), key=lambda kv: -kv[1]["calls"]):
            lat = sorted(o.pop("_lat"))
            by_operation.append({"name": key, **o, "p95_ms": _pct(lat, 0.95)})

        prev = self._all_since(since - hours * 3600, org_id, until=since)
        last = traces[-1].created_at if traces else self._last(org_id)
        return {
            "window_hours": hours,
            "bucket_seconds": step,
            "requests": total,
            "requests_with_detections": with_det,
            "detection_rate": round(with_det / total, 4) if total else 0.0,
            "detections": detections,
            "entities_per_request": round(detections / with_det, 1) if with_det else 0.0,
            "anonymized_entities": anonymized,
            "anonymization_rate": round(anonymized / detections, 4) if detections else 0.0,
            "not_allowed": len(not_allowed),
            "block_rate": round(len(not_allowed) / total, 4) if total else 0.0,
            "needs_review": sum(1 for t in traces if t.needs_review),
            "with_warnings": sum(1 for t in traces if t.warnings),
            "observe_mode": sum(1 for t in traces if t.mode == "observe"),
            "resources_read": len({t.resource for t in traces if t.resource}),
            "result_chars": sum(t.result_chars or 0 for t in traces),
            "by_outcome": dict(Counter(t.outcome or "n/a" for t in traces)),
            "by_risk": dict(Counter(t.risk or "n/a" for t in traces)),
            "by_route": dict(Counter(t.route for t in traces)),
            "by_provider": dict(Counter(t.provider for t in traces if t.provider)),
            "by_policy": dict(Counter(t.policy for t in traces if t.policy)),
            "by_operation": by_operation,
            "top_fields": dict(fields.most_common(10)),
            "warnings": dict(Counter(w for t in traces for w in t.warnings).most_common(5)),
            "entity_distribution": dict(entity_dist.most_common()),
            "actions": dict(actions),
            "latency_ms": {
                "avg": round(sum(latencies) / len(latencies), 1) if latencies else None,
                "p50": _pct(latencies, 0.5),
                "p95": _pct(latencies, 0.95),
                "p99": _pct(latencies, 0.99),
            },
            "errors": sum(1 for t in traces if t.status >= 500),
            "previous": {
                "requests": len(prev),
                "detections": sum(sum(t.entity_counts.values()) for t in prev),
                "not_allowed": sum(1 for t in prev if t.outcome and t.outcome != "allow"),
                "errors": sum(1 for t in prev if t.status >= 500),
            },
            "last_trace_at": last,
            "timeseries": series,
        }

    def _last(self, org_id: str) -> float | None:
        with self._lock:
            row = self._db.execute("SELECT MAX(created_at) FROM traces WHERE org_id = ?", (org_id,)).fetchone()
        return row[0] if row and row[0] is not None else None

    def _all_since(self, since: float, org_id: str, until: float | None = None) -> list[Trace]:
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM traces WHERE org_id = ? AND created_at >= ? AND created_at < ? ORDER BY created_at",
                (org_id, since, until if until is not None else 1e18)).fetchall()
        return [Trace.model_validate_json(r[0]) for r in rows]
