"""Corrections from the Chat tab: what should have been detected and what was detected wrongly.

Feedback holds the raw text, because a correction is useless without it. It is therefore meant for test
data, stays in its own SQLite file next to the other stores, is readable by admins only, never goes into
traces and is exported only on request. The audit log records who gave feedback, never the text.

Export format (one JSON object per line), the gold format of ``anonymizer.ner_dataset`` plus negatives:

    {"key": "feedback:fb_…", "split": "", "text": "…",
     "spans": [{"start", "end", "label", "text"}],   # should be detected; NER labels PER/ORG/LOC/ADDR, else type
     "reject": [{"start", "end", "text", "was"}]}     # detected, but is not protected data (``was``: the type)

``ner_train.py --feedback`` trains on it as partial annotation: confirmed entities, confirmed non-entities
(taught as O) and every other token left out of the loss.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# Types a correction may name. person/organization/location/address map to the NER labels of the gold set.
FEEDBACK_TYPES = ("person", "organization", "location", "address", "case_number", "court", "legal_citation",
                  "date", "iban", "email", "phone", "other")
NER_LABEL = {"person": "PER", "organization": "ORG", "location": "LOC", "address": "ADDR"}
MAX_TEXT = 20_000


class FeedbackError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def validate(text: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean span list: inside the text, known kind and type, no duplicates, sorted."""
    if not text.strip():
        raise FeedbackError("text is empty")
    if len(text) > MAX_TEXT:
        raise FeedbackError(f"text exceeds {MAX_TEXT} characters")
    if not spans:
        raise FeedbackError("mark at least one span")
    out, seen = [], set()
    for s in spans:
        start, end, kind = int(s["start"]), int(s["end"]), s["kind"]
        label = s.get("label") or ""
        if not 0 <= start < end <= len(text):
            raise FeedbackError(f"span {start}-{end} is outside the text")
        if kind not in ("missed", "wrong"):
            raise FeedbackError("kind must be missed or wrong")
        if kind == "missed" and label not in FEEDBACK_TYPES:
            raise FeedbackError(f"unknown type {label!r}; use one of {', '.join(FEEDBACK_TYPES)}")
        if not text[start:end].strip():
            raise FeedbackError("span is only whitespace")
        key = (start, end, kind)
        if key not in seen:
            seen.add(key)
            out.append({"start": start, "end": end, "kind": kind, "label": label})
    return sorted(out, key=lambda s: (s["start"], s["end"]))


class FeedbackStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY, org_id TEXT NOT NULL, created_at REAL NOT NULL, created_by TEXT,
            text TEXT NOT NULL, spans TEXT NOT NULL, policy TEXT, trace_id TEXT)""")
        self._db.execute("CREATE INDEX IF NOT EXISTS feedback_org ON feedback(org_id, created_at)")
        self._db.commit()

    def add(self, org_id: str, text: str, spans: list[dict[str, Any]], created_by: str,
            policy: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        spans = validate(text, spans)
        row = {"id": f"fb_{uuid.uuid4().hex[:12]}", "created_at": time.time(), "created_by": created_by,
               "text": text, "spans": spans, "policy": policy, "trace_id": trace_id}
        with self._lock:
            self._db.execute("INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?)",
                             (row["id"], org_id, row["created_at"], created_by, text, json.dumps(spans), policy, trace_id))
            self._db.commit()
        return row

    def list(self, org_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, created_at, created_by, text, spans, policy, trace_id FROM feedback WHERE org_id = ? "
                "ORDER BY created_at DESC LIMIT ?", (org_id, min(max(limit, 1), 10_000))).fetchall()
        return [{"id": r[0], "created_at": r[1], "created_by": r[2], "text": r[3], "spans": json.loads(r[4]),
                 "policy": r[5], "trace_id": r[6]} for r in rows]

    def delete(self, org_id: str, feedback_id: str) -> bool:
        with self._lock:
            n = self._db.execute("DELETE FROM feedback WHERE org_id = ? AND id = ?", (org_id, feedback_id)).rowcount
            self._db.commit()
        return bool(n)

    def export(self, org_id: str) -> str:
        """All feedback of the organisation as gold JSONL (see module doc)."""
        lines = []
        for row in reversed(self.list(org_id, 10_000)):
            text = row["text"]
            spans = [{"start": s["start"], "end": s["end"], "label": NER_LABEL.get(s["label"], s["label"]),
                      "text": text[s["start"]:s["end"]]} for s in row["spans"] if s["kind"] == "missed"]
            reject = [{"start": s["start"], "end": s["end"], "text": text[s["start"]:s["end"]], "was": s["label"]}
                      for s in row["spans"] if s["kind"] == "wrong"]
            lines.append(json.dumps({"key": f"feedback:{row['id']}", "split": "", "text": text, "spans": spans,
                                     "reject": reject}, ensure_ascii=False))
        return "\n".join(lines) + ("\n" if lines else "")
