"""Playground: upload a CSV, query it, and see exactly what an AI client would receive.

A dataset is a CSV file stored in SQLite (``ANONYMIZER_PLAYGROUND_DB``, default ``data/playground.db``),
scoped to one organization. Queries run the same protection as the MCP proxy (:class:`ResultFilter`):
rows are sent as a JSON array, column names act as field hints (``vorname``, ``email``, ``iban`` ...),
and values learned from hinted columns are also found in free-text columns.

* ``query(..., include_original=True)`` is for the dashboard only: it returns each row before and after
  protection, so a person can compare. The API exposes it to dashboard sessions, never to API keys.
* The MCP tools only ever get the protected rows.
* Every query writes a trace (route ``/v1/playground``; resource = dataset id) and an audit entry.
  With content traces on, the trace keeps the original and the protected value of every changed cell.

Playground data is meant for test data. The stored CSV is personal data in clear text if you upload
real data; delete datasets when done.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import mcp_types as types

from anonymizer.accounts import Principal
from anonymizer.proxy.config import DEFAULT_FIELD_HINTS
from anonymizer.proxy.filter import KnownValues, ResultFilter
from anonymizer.tracing import Trace, TraceStep, TraceStore
from anonymizer.vault import InMemoryVault, VaultKey

MAX_BYTES = 100 * 1024 * 1024  # a full chatbot sessions export (one row per message) is about 100 MB
MAX_ROWS = 2_000_000
MAX_COLUMNS = 100
MAX_LIMIT = 100
_SEP = "\x1f"

csv.field_size_limit(MAX_BYTES)  # chat messages with widget JSON exceed the default 128 KB per field


def _search_text(row: dict[str, str], columns: list[str]) -> str:
    """Lower-cased values joined by a separator a query cannot contain: lets SQLite filter rows."""
    return _SEP.join((row.get(c) or "").lower() for c in columns)


class PlaygroundError(RuntimeError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class PlaygroundStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        if self.path != ":memory:":  # faster bulk inserts, readers do not block the writer
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL, columns TEXT NOT NULL,
                rows INTEGER NOT NULL, created_at REAL NOT NULL, created_by TEXT);
            CREATE TABLE IF NOT EXISTS query_cache (
                dataset_id TEXT NOT NULL, key TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY (dataset_id, key));
            CREATE TABLE IF NOT EXISTS dataset_rows (
                dataset_id TEXT NOT NULL, idx INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (dataset_id, idx));
        """)
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(dataset_rows)")}
        if "search" not in cols:  # stores from before text search ran in SQLite
            self._db.execute("ALTER TABLE dataset_rows ADD COLUMN search TEXT")
            for ds_id, columns in self._db.execute("SELECT id, columns FROM datasets").fetchall():
                cs = json.loads(columns)
                rows = self._db.execute("SELECT idx, data FROM dataset_rows WHERE dataset_id = ?", (ds_id,)).fetchall()
                self._db.executemany("UPDATE dataset_rows SET search = ? WHERE dataset_id = ? AND idx = ?",
                                     [(_search_text(json.loads(d), cs), ds_id, i) for i, d in rows])
        self._db.commit()

    def add(self, org_id: str, name: str, columns: list[str], rows: list[dict[str, str]], created_by: str) -> dict:
        ds = {"id": f"ds_{uuid.uuid4().hex[:10]}", "org_id": org_id, "name": name, "columns": columns,
              "rows": len(rows), "created_at": time.time(), "created_by": created_by}
        with self._lock:
            self._db.execute("INSERT INTO datasets VALUES (?,?,?,?,?,?,?)",
                             (ds["id"], org_id, name, json.dumps(columns), len(rows), ds["created_at"], created_by))
            self._db.executemany("INSERT INTO dataset_rows (dataset_id, idx, data, search) VALUES (?,?,?,?)",
                                 ((ds["id"], i, json.dumps(r, ensure_ascii=False), _search_text(r, columns))
                                  for i, r in enumerate(rows)))
            self._db.commit()
        return ds

    def list(self, org_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, org_id, name, columns, rows, created_at, created_by FROM datasets "
                                    "WHERE org_id = ? ORDER BY created_at DESC", (org_id,)).fetchall()
        return [self._head(r) for r in rows]

    def get(self, org_id: str, dataset_id: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT id, org_id, name, columns, rows, created_at, created_by FROM datasets "
                                 "WHERE org_id = ? AND id = ?", (org_id, dataset_id)).fetchone()
        return self._head(r) if r else None

    def rows(self, dataset_id: str) -> list[tuple[int, dict[str, str]]]:
        with self._lock:
            rows = self._db.execute("SELECT idx, data FROM dataset_rows WHERE dataset_id = ? ORDER BY idx",
                                    (dataset_id,)).fetchall()
        return [(i, json.loads(d)) for i, d in rows]

    def search(self, dataset_id: str, needle: str, columns: list[str] | None,
               offset: int, limit: int) -> tuple[int, list[dict[str, str]]]:
        """(number of matching rows, one page of them). ``needle`` is lower-case; empty matches all rows.
        Filtering, counting and paging run in SQLite, so a 100 MB dataset is never loaded as a whole.
        With ``columns`` (a subset) SQLite pre-filters on all columns and Python checks the subset."""
        needle = needle.replace(_SEP, "")
        where, args = "dataset_id = ?", [dataset_id]
        if needle:
            where += " AND instr(search, ?) > 0"
            args.append(needle)
        with self._lock:
            if not needle and columns is None:
                # rows are numbered 0..n-1: count from the dataset header and page by index (no scan, no OFFSET)
                row = self._db.execute("SELECT rows FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
                page = self._db.execute("SELECT data FROM dataset_rows WHERE dataset_id = ? AND idx >= ? "
                                        "ORDER BY idx LIMIT ?", (dataset_id, offset, limit)).fetchall()
                return (row[0] if row else 0), [json.loads(d) for (d,) in page]
            if not needle or columns is None:
                total = self._db.execute(f"SELECT COUNT(*) FROM dataset_rows WHERE {where}", args).fetchone()[0]
                page = self._db.execute(f"SELECT data FROM dataset_rows WHERE {where} ORDER BY idx LIMIT ? OFFSET ?",
                                        [*args, limit, offset]).fetchall()
                return total, [json.loads(d) for (d,) in page]
            total, out = 0, []
            for (d,) in self._db.execute(f"SELECT data FROM dataset_rows WHERE {where} ORDER BY idx", args):
                r = json.loads(d)
                if any(needle in (r.get(c) or "").lower() for c in columns):
                    if offset <= total < offset + limit:
                        out.append(r)
                    total += 1
            return total, out

    def delete(self, org_id: str, dataset_id: str) -> bool:
        with self._lock:
            n = self._db.execute("DELETE FROM datasets WHERE org_id = ? AND id = ?", (org_id, dataset_id)).rowcount
            if n:
                self._db.execute("DELETE FROM dataset_rows WHERE dataset_id = ?", (dataset_id,))
                self._db.execute("DELETE FROM query_cache WHERE dataset_id = ?", (dataset_id,))
            self._db.commit()
        return bool(n)

    def cached(self, dataset_id: str, key: str) -> dict | None:
        """A stored dashboard result: shown again without running detection."""
        with self._lock:
            r = self._db.execute("SELECT result FROM query_cache WHERE dataset_id = ? AND key = ?",
                                 (dataset_id, key)).fetchone()
        return json.loads(r[0]) if r else None

    def cache(self, dataset_id: str, key: str, result: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO query_cache VALUES (?,?,?,?)",
                             (dataset_id, key, json.dumps(result, ensure_ascii=False), time.time()))
            self._db.commit()

    @staticmethod
    def _head(r) -> dict:
        return {"id": r[0], "name": r[2], "columns": json.loads(r[3]), "rows": r[4], "created_at": r[5],
                "created_by": r[6]}


def parse_csv(data: bytes | str) -> tuple[list[str], list[dict[str, str]]]:
    """CSV with a header row; delimiter , ; or tab is detected. UTF-8 (with or without BOM) or cp1252."""
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise PlaygroundError(f"file larger than {MAX_BYTES // (1024 * 1024)} MB", 413)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    else:
        text = data
    if not text.strip():
        raise PlaygroundError("empty file")
    sample = text[:20_000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, None)
    if not header:
        raise PlaygroundError("no header row")
    columns, seen = [], set()
    for i, h in enumerate(header[:MAX_COLUMNS]):
        name = (h or "").strip() or f"column_{i + 1}"
        while name in seen:
            name += "_"
        seen.add(name)
        columns.append(name)
    rows = []
    for rec in reader:
        if not any((c or "").strip() for c in rec):
            continue
        if len(rows) >= MAX_ROWS:
            raise PlaygroundError(f"more than {MAX_ROWS} rows", 413)
        rows.append({c: (rec[i] if i < len(rec) else "") for i, c in enumerate(columns)})
    if not rows:
        raise PlaygroundError("no data rows")
    return columns, rows


class PlaygroundService:
    def __init__(self, store: PlaygroundStore, pipeline_factory: Callable[[Any], Any], policy: str,
                 traces: TraceStore | None = None, audit=None, destination: str = "external") -> None:
        self.store = store
        self.pipeline_factory = pipeline_factory
        self.policy = policy
        self.traces = traces
        self.audit = audit
        self.destination = destination

    # -- datasets ------------------------------------------------------------------------------
    def upload(self, principal: Principal, name: str, data: bytes | str) -> dict:
        columns, rows = parse_csv(data)
        name = (name or "dataset.csv").strip()[:120]
        ds = self.store.add(principal.org_id, name, columns, rows, principal.label)
        self._audit(principal, "create", ds["id"], {"name": name, "rows": len(rows), "columns": columns})
        ds.pop("org_id", None)
        try:  # warm the default dashboard view (first 20 rows) so the first click is instant
            self.query(principal, ds["id"], None, None, 20, 0, include_original=True, client="dashboard")
        except Exception:  # noqa: BLE001 - the upload itself succeeded; the view is computed on first open instead
            pass
        return ds

    def list(self, principal: Principal) -> list[dict]:
        return self.store.list(principal.org_id)

    def delete(self, principal: Principal, dataset_id: str) -> None:
        if not self.store.delete(principal.org_id, dataset_id):
            raise PlaygroundError("dataset not found", 404)
        self._audit(principal, "delete", dataset_id, None)

    # -- query ---------------------------------------------------------------------------------
    def query(self, principal: Principal, dataset_id: str, query: str | None = None,
              columns: list[str] | None = None, limit: int = 20, offset: int = 0,
              include_original: bool = False, client: str = "api") -> dict[str, Any]:
        """Filter rows (case-insensitive substring over all or the given columns), protect them as one JSON
        result and return what the client receives. Protection is the MCP proxy filter."""
        t0 = time.perf_counter()
        ds = self.store.get(principal.org_id, dataset_id)
        if ds is None:
            raise PlaygroundError("dataset not found; list datasets first", 404)
        cols = [c for c in (columns or ds["columns"]) if c in ds["columns"]] or ds["columns"]
        limit = max(1, min(int(limit), MAX_LIMIT))
        offset = max(0, int(offset))
        needle = (query or "").strip().lower()
        # Dashboard views are stored: once an upload page was anonymized it is shown again from the store.
        # The key covers everything that changes the result (query, columns, page, policy).
        cache_key = (json.dumps([needle, cols, limit, offset, self.policy, self.destination])
                     if include_original and client == "dashboard" else None)
        if cache_key and (hit := self.store.cached(dataset_id, cache_key)) is not None:
            return hit
        n_matched, page = self.store.search(dataset_id, needle, None if cols == ds["columns"] else cols,
                                            offset, limit)
        originals = [{c: r.get(c, "") for c in cols} for r in page]

        pipeline = self.pipeline_factory(InMemoryVault(VaultKey.generate()))
        filt = ResultFilter(pipeline, self.destination, f"{principal.org_id}\x1fplayground:{dataset_id}",
                            observe=False, hints=DEFAULT_FIELD_HINTS, known=KnownValues())
        raw = types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(originals, ensure_ascii=False))])
        result, report = filt.apply(raw)
        sent_text = result.content[0].text if result.content and isinstance(result.content[0], types.TextContent) else "[]"
        try:
            protected = json.loads(sent_text)
        except ValueError:  # whole result withheld (too large): keep the notice
            protected = None

        latency = round((time.perf_counter() - t0) * 1000, 1)
        trace = report.trace(upstream="playground", tool="query_dataset" if client == "mcp" else "dashboard",
                             mode="enforce", provider="playground", model=ds["name"], latency_ms=latency)
        trace.route = "/v1/playground"
        trace.resource = dataset_id
        trace.steps = [
            TraceStep(name="Tool call", detail=f"playground · {client} · {ds['name']}"),
            TraceStep(name="Query", detail=f"{n_matched} matching row(s) of {ds['rows']}"
                                           f"{' for ' + repr(query) if needle else ''} · returned {len(page)}"),
            TraceStep(name="Privacy detection", detail=f"{report.values} values analysed · {report.changed} changed · "
                                                       f"{report.hinted} by column name · {report.learned} known value(s)",
                      status="warning" if report.warnings else "ok"),
            TraceStep(name="Policy evaluation", detail=f"{self.policy} · {report.withheld} value(s) withheld",
                      status="blocked" if report.withheld else "ok"),
        ]
        if self.traces is not None:
            self.traces.add(trace, principal.org_id)
        self._audit(principal, "query", dataset_id, {"query": bool(needle), "rows": len(page), "client": client})

        out: dict[str, Any] = {
            "dataset": {k: ds[k] for k in ("id", "name", "rows")},
            "columns": cols, "matched": n_matched, "offset": offset, "limit": limit,
            "rows": protected if protected is not None else sent_text,
            "trace_id": trace.id,
        }
        if include_original:
            out["original"] = originals
            out["sent"] = sent_text
            out["replacements"] = _replacements(report)
            out["entities"] = dict(trace.entity_counts)
            out["withheld"] = report.withheld
        if cache_key:
            self.store.cache(dataset_id, cache_key, out)
        return out

    def _audit(self, principal: Principal, action: str, dataset_id: str, after: Any) -> None:
        if self.audit is not None:
            self.audit.record(principal.org_id, action, "playground_dataset", dataset_id, principal, after=after)


def _replacements(report) -> list[dict[str, Any]]:
    """Original value -> placeholder per changed value, from the per-value traces of the filter."""
    seen, out = set(), []
    for part in report.parts:
        for c in part.content:
            for r in c.replacements:
                key = (r.type, r.original, r.replacement)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"type": r.type, "original": r.original, "replacement": r.replacement,
                            "field": c.label, "method": r.method})
    return out
