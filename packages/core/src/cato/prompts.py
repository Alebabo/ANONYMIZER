"""Prompt management: versions, labels, diffs, with a privacy check on every write.

Backends (``CATO_PROMPTS``):

* ``local``    SQLite, append-only versions, labels per organization
* ``langfuse`` Langfuse prompt management via the public API (single organization: the default org)

Rules enforced here, independent of the backend:

* **Scan before save.** A new version is rejected if it contains anything
  classified ``sensitive`` or ``critical`` (customer names, e-mails, IBANs,
  health data, ...). This keeps customer examples out of prompts.
* **No placeholders in drafts.** A draft containing Cato placeholders
  (``PERSON_001``) would write pseudonyms back over real values; it is
  rejected.
* **Reads are protected.** If a stored prompt (e.g. created outside Cato)
  contains sensitive data, readers get the anonymized text and
  ``protected: true``.
* **Labels are separate from versions.** Creating a version never moves a
  label. Moving a label (e.g. ``production``) is an admin action; the MCP
  server has no tool for it.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field

from cato.accounts import DEFAULT_ORG

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}")
LABEL = re.compile(r"[a-z0-9][a-z0-9_\-]{0,31}")
RESERVED_LABELS = {"latest"}
PLACEHOLDER = re.compile(r"\b[A-Z][A-Z_]{1,40}_\d{3,}\b|\[REDACTED\]")
MAX_PROMPT_CHARS = 100_000
# Entity types a prompt may contain (company names, places, dates, amounts, public references).
BENIGN_TYPES = {"organization", "location", "date", "money", "court", "legal_citation", "privilege_marker",
                "business_secret_marker"}

PromptType = Literal["text", "chat"]


class PromptError(RuntimeError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class ChatMessage(BaseModel):
    role: str
    content: str


class PromptVersion(BaseModel):
    name: str
    version: int
    type: PromptType = "text"
    prompt: str | list[ChatMessage]
    config: dict[str, Any] = Field(default_factory=dict)
    labels: list[str] = Field(default_factory=list)
    note: str | None = None
    created_by: str | None = None
    created_at: float | None = None
    hash: str = ""

    def texts(self) -> list[str]:
        return [self.prompt] if isinstance(self.prompt, str) else [m.content for m in self.prompt]

    def rendered(self) -> str:
        if isinstance(self.prompt, str):
            return self.prompt
        return "\n\n".join(f"[{m.role}]\n{m.content}" for m in self.prompt)


class PromptSummary(BaseModel):
    name: str
    latest_version: int
    versions: int
    labels: dict[str, int] = Field(default_factory=dict)  # label -> version
    updated_at: float | None = None


def content_hash(prompt: str | list[ChatMessage], config: dict[str, Any]) -> str:
    body = prompt if isinstance(prompt, str) else [m.model_dump() for m in prompt]
    raw = json.dumps({"prompt": body, "config": config}, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def check_name(name: str) -> str:
    if not NAME.fullmatch(name or ""):
        raise PromptError("invalid prompt name (letters, digits, _ . -; max. 128)", 422)
    return name


def check_label(label: str) -> str:
    if not LABEL.fullmatch(label or "") or label in RESERVED_LABELS:
        raise PromptError("invalid label (lowercase letters, digits, _ -; max. 32; 'latest' is reserved)", 422)
    return label


class PromptBackend(Protocol):
    kind: str

    def list(self, org_id: str) -> list[PromptSummary]: ...
    def get(self, org_id: str, name: str, version: int | None = None, label: str | None = None) -> PromptVersion: ...
    def history(self, org_id: str, name: str) -> list[PromptVersion]: ...
    def create(self, org_id: str, name: str, type_: PromptType, prompt: str | list[ChatMessage],
               config: dict[str, Any], note: str | None, created_by: str | None) -> PromptVersion: ...
    def set_label(self, org_id: str, name: str, version: int, label: str) -> tuple[int | None, int]: ...


# -- local backend ---------------------------------------------------------------

class LocalPromptBackend:
    kind = "local"

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS prompt_versions (
                org_id TEXT NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL, type TEXT NOT NULL,
                prompt TEXT NOT NULL, config TEXT NOT NULL, note TEXT, created_by TEXT, created_at REAL NOT NULL,
                hash TEXT NOT NULL, PRIMARY KEY (org_id, name, version));
            CREATE TABLE IF NOT EXISTS prompt_labels (
                org_id TEXT NOT NULL, name TEXT NOT NULL, label TEXT NOT NULL, version INTEGER NOT NULL,
                updated_at REAL NOT NULL, PRIMARY KEY (org_id, name, label));
        """)
        self._db.commit()

    def _labels(self, org_id: str, name: str) -> dict[str, int]:
        rows = self._db.execute("SELECT label, version FROM prompt_labels WHERE org_id = ? AND name = ?",
                                (org_id, name)).fetchall()
        return {r["label"]: r["version"] for r in rows}

    def _row(self, row: sqlite3.Row, labels: dict[str, int], latest: int) -> PromptVersion:
        prompt = row["prompt"] if row["type"] == "text" else [ChatMessage(**m) for m in json.loads(row["prompt"])]
        lab = sorted(lbl for lbl, v in labels.items() if v == row["version"])
        if row["version"] == latest:
            lab.append("latest")
        return PromptVersion(name=row["name"], version=row["version"], type=row["type"], prompt=prompt,
                             config=json.loads(row["config"]), labels=lab, note=row["note"],
                             created_by=row["created_by"], created_at=row["created_at"], hash=row["hash"])

    def _latest(self, org_id: str, name: str) -> int | None:
        row = self._db.execute("SELECT MAX(version) FROM prompt_versions WHERE org_id = ? AND name = ?",
                               (org_id, name)).fetchone()
        return row[0]

    def list(self, org_id: str) -> list[PromptSummary]:
        with self._lock:
            rows = self._db.execute(
                "SELECT name, MAX(version) AS latest, COUNT(*) AS n, MAX(created_at) AS updated "
                "FROM prompt_versions WHERE org_id = ? GROUP BY name ORDER BY name", (org_id,)).fetchall()
            return [PromptSummary(name=r["name"], latest_version=r["latest"], versions=r["n"],
                                  labels=self._labels(org_id, r["name"]), updated_at=r["updated"]) for r in rows]

    def get(self, org_id: str, name: str, version: int | None = None, label: str | None = None) -> PromptVersion:
        with self._lock:
            latest = self._latest(org_id, name)
            if latest is None:
                raise PromptError("prompt not found", 404)
            labels = self._labels(org_id, name)
            if version is None:
                if label and label != "latest":
                    if label not in labels:
                        raise PromptError(f"label {label!r} not set on this prompt", 404)
                    version = labels[label]
                else:
                    version = latest
            row = self._db.execute("SELECT * FROM prompt_versions WHERE org_id = ? AND name = ? AND version = ?",
                                   (org_id, name, version)).fetchone()
            if row is None:
                raise PromptError("prompt version not found", 404)
            return self._row(row, labels, latest)

    def history(self, org_id: str, name: str) -> list[PromptVersion]:
        with self._lock:
            latest = self._latest(org_id, name)
            if latest is None:
                raise PromptError("prompt not found", 404)
            labels = self._labels(org_id, name)
            rows = self._db.execute("SELECT * FROM prompt_versions WHERE org_id = ? AND name = ? ORDER BY version DESC",
                                    (org_id, name)).fetchall()
            return [self._row(r, labels, latest) for r in rows]

    def create(self, org_id, name, type_, prompt, config, note, created_by) -> PromptVersion:
        body = prompt if isinstance(prompt, str) else json.dumps([m.model_dump() for m in prompt], ensure_ascii=False)
        with self._lock:
            version = (self._latest(org_id, name) or 0) + 1
            now = time.time()
            self._db.execute("INSERT INTO prompt_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (org_id, name, version, type_, body, json.dumps(config, ensure_ascii=False), note,
                              created_by, now, content_hash(prompt, config)))
            self._db.commit()
        return self.get(org_id, name, version)

    def set_label(self, org_id: str, name: str, version: int, label: str) -> tuple[int | None, int]:
        with self._lock:
            exists = self._db.execute("SELECT 1 FROM prompt_versions WHERE org_id = ? AND name = ? AND version = ?",
                                      (org_id, name, version)).fetchone()
            if not exists:
                raise PromptError("prompt version not found", 404)
            before = self._labels(org_id, name).get(label)
            self._db.execute("INSERT INTO prompt_labels VALUES (?,?,?,?,?) ON CONFLICT (org_id, name, label) "
                             "DO UPDATE SET version = excluded.version, updated_at = excluded.updated_at",
                             (org_id, name, label, version, time.time()))
            self._db.commit()
        return before, version


# -- langfuse backend --------------------------------------------------------------

class LangfusePromptBackend:
    """Langfuse prompt management (``/api/public/v2/prompts``). Langfuse projects have no notion of
    Cato organizations, so only the default organization may use this backend."""

    kind = "langfuse"

    def __init__(self, base_url: str, public_key: str, secret_key: str, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not (base_url and public_key and secret_key):
            raise PromptError("the langfuse prompt backend needs CATO_PROMPTS_URL, CATO_PROMPTS_PUBLIC_KEY and "
                              "CATO_PROMPTS_SECRET_KEY (or the CATO_SOURCE_* Langfuse settings)", 500)
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, auth=(public_key, secret_key), timeout=timeout,
                                   transport=transport)

    @staticmethod
    def _org(org_id: str) -> None:
        if org_id != DEFAULT_ORG:
            raise PromptError("the Langfuse prompt backend is only available to the default organization", 403)

    def _call(self, method: str, path: str, **kw) -> Any:
        try:
            r = self.client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise PromptError(f"Langfuse unreachable ({type(exc).__name__})", 502) from None
        if r.status_code == 404:
            raise PromptError("prompt not found", 404)
        if r.status_code >= 400:
            raise PromptError(f"Langfuse returned HTTP {r.status_code}", 502)
        try:
            return r.json()
        except ValueError:
            raise PromptError("Langfuse returned invalid JSON", 502) from None

    @staticmethod
    def _version(body: dict[str, Any]) -> PromptVersion:
        type_ = "chat" if body.get("type") == "chat" or isinstance(body.get("prompt"), list) else "text"
        raw = body.get("prompt")
        prompt: str | list[ChatMessage]
        if type_ == "chat":
            prompt = [ChatMessage(role=str(m.get("role", "")), content=str(m.get("content", "")))
                      for m in raw or [] if isinstance(m, dict)]
        else:
            prompt = str(raw or "")
        config = body.get("config") if isinstance(body.get("config"), dict) else {}
        created = body.get("createdAt") or body.get("updatedAt")
        from cato.sources import _ts

        return PromptVersion(name=str(body.get("name")), version=int(body.get("version", 0)), type=type_,
                             prompt=prompt, config=config, labels=sorted(map(str, body.get("labels") or [])),
                             note=body.get("commitMessage"), created_by=body.get("createdBy"),
                             created_at=_ts(created) if created else None, hash=content_hash(prompt, config))

    def list(self, org_id: str) -> list[PromptSummary]:
        self._org(org_id)
        out, page = [], 1
        while page <= 20:
            body = self._call("GET", "/api/public/v2/prompts", params={"page": page, "limit": 100})
            for p in body.get("data", []):
                versions = [int(v) for v in p.get("versions") or []]
                out.append(PromptSummary(name=str(p.get("name")), latest_version=max(versions, default=0),
                                         versions=len(versions), labels={}, updated_at=None))
            meta = body.get("meta", {})
            if page >= int(meta.get("totalPages") or 1):
                break
            page += 1
        return sorted(out, key=lambda s: s.name)

    def get(self, org_id: str, name: str, version: int | None = None, label: str | None = None) -> PromptVersion:
        self._org(org_id)
        params = {"version": version} if version is not None else {"label": label or "latest"}
        return self._version(self._call("GET", f"/api/public/v2/prompts/{_q(name)}", params=params))

    def history(self, org_id: str, name: str) -> list[PromptVersion]:
        self._org(org_id)
        body = self._call("GET", "/api/public/v2/prompts", params={"name": name, "limit": 1})
        match = next((p for p in body.get("data", []) if p.get("name") == name), None)
        if match is None:
            raise PromptError("prompt not found", 404)
        versions = sorted((int(v) for v in match.get("versions") or []), reverse=True)[:50]
        return [self.get(org_id, name, v) for v in versions]

    def create(self, org_id, name, type_, prompt, config, note, created_by) -> PromptVersion:
        self._org(org_id)
        body: dict[str, Any] = {
            "name": name, "type": type_, "labels": [], "config": config,
            "prompt": prompt if isinstance(prompt, str) else [m.model_dump() for m in prompt],
        }
        if note:
            body["commitMessage"] = note
        return self._version(self._call("POST", "/api/public/v2/prompts", json=body))

    def set_label(self, org_id: str, name: str, version: int, label: str) -> tuple[int | None, int]:
        self._org(org_id)
        try:
            before = self.get(org_id, name, label=label).version
        except PromptError as exc:
            if exc.status != 404:
                raise
            before = None
        current = self.get(org_id, name, version)
        labels = sorted(set(current.labels) - {"latest"} | {label})
        self._call("PATCH", f"/api/public/v2/prompts/{_q(name)}/versions/{version}", json={"newLabels": labels})
        return before, version


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


# -- service -------------------------------------------------------------------------

class PromptService:
    """Backend plus the privacy rules. ``detector``/``classifier`` come from the caller so that the same
    models apply as everywhere else; ``protect_text(text) -> str | None`` anonymizes a stored prompt with
    the active policy for reading (``None`` if the policy does not allow it)."""

    def __init__(self, backend: PromptBackend, detector, classifier, protect_text, audit=None) -> None:
        self.backend = backend
        self.detector = detector
        self.classifier = classifier
        self.protect_text = protect_text
        self.audit = audit
        # Same patterns, no statistical NER: the deterministic half of the check.
        from cato.detect import Detector

        self._rules = Detector(detector.config.model_copy(update={"enable_ner": False}))

    # -- privacy checks ----------------------------------------------------------
    def _types(self, detector, text: str) -> set[str]:
        scan = detector.scan(text)
        c = self.classifier.classify_text(text, scan)
        return {e.entity_type for e in c.entities
                if e.risk.value in ("sensitive", "critical") or e.entity_type not in BENIGN_TYPES}

    def _findings(self, text: str) -> tuple[list[str], list[str]]:
        """``(hard, soft)`` entity types that must not be in a prompt.

        *hard*: found by deterministic recognizers (e-mail, IBAN, phone, address, honorific + name,
        self-introductions, custom patterns). These block a write and anonymize a read.
        *soft*: found only by statistical NER. German imperatives ("Nenne", "Kurz") and persona names
        ("Lisa") trip it constantly, so these are reported as warnings for the human who promotes the
        version instead of blocking every German prompt.

        Context such as "example" lowers the risk of a name, but a real customer labelled as an example
        is still a real customer, so every type outside :data:`BENIGN_TYPES` counts regardless of risk."""
        hard = self._types(self._rules, text)
        scan = self.detector.scan(text)
        c = self.classifier.classify_text(text, scan)
        by_id = {d.id: d for d in scan.detections}
        soft: set[str] = set()
        for e in c.entities:
            if not (e.risk.value in ("sensitive", "critical") or e.entity_type not in BENIGN_TYPES):
                continue
            det = by_id.get(e.detection_id)
            # A full name (first and last) is a person even when only NER found it.
            if e.entity_type == "person" and det is not None and len(text[det.start:det.end].split()) >= 2:
                hard.add("person")
            else:
                soft.add(e.entity_type)
        return sorted(hard), sorted(soft - hard)

    def _check_write(self, prompt: str | list[ChatMessage]) -> list[str]:
        texts = [prompt] if isinstance(prompt, str) else [m.content for m in prompt]
        total = sum(len(t) for t in texts)
        if not total or not any(t.strip() for t in texts):
            raise PromptError("prompt is empty", 422)
        if total > MAX_PROMPT_CHARS:
            raise PromptError(f"prompt exceeds {MAX_PROMPT_CHARS} characters", 413)
        warnings: set[str] = set()
        for t in texts:
            if PLACEHOLDER.search(t):
                raise PromptError("prompt contains Cato placeholders (e.g. PERSON_001 or [REDACTED]); "
                                  "write the real template text instead of pasting protected output", 422)
            hard, soft = self._findings(t)
            if hard:
                raise PromptError("prompt contains sensitive data and was not saved: " + ", ".join(hard)
                                  + ". Use template variables such as {{customer_name}} instead.", 422)
            warnings.update(soft)
        return sorted(warnings)

    def _protect(self, v: PromptVersion) -> dict[str, Any]:
        """Readable as stored, unless it contains sensitive data; then anonymized and flagged."""
        out = v.model_dump(mode="json")
        findings = [self._findings(text) for text in v.texts()]
        risky = sorted({t for hard, _ in findings for t in hard})
        soft = sorted({t for _, s in findings for t in s} - set(risky))
        out["protected"] = bool(risky)
        if soft:
            out["warnings"] = [f"possibly contains {t} (statistical detection; check before promoting)"
                               for t in soft]
        # Notes and config can come from outside Cato (Langfuse commit messages); same rule.
        if v.note and self._findings(v.note)[0]:
            out["note"] = self.protect_text(v.note)
            out["protected"] = True
        if v.config and self._findings(json.dumps(v.config, ensure_ascii=False))[0]:
            out["config"] = {"withheld": "config contains sensitive data"}
            out["protected"] = True
        if risky:
            safe = self.protect_text
            if isinstance(v.prompt, str):
                out["prompt"] = safe(v.prompt)
            else:
                out["prompt"] = [{"role": m.role, "content": safe(m.content)} for m in v.prompt]
            out["notice"] = ("This prompt contains sensitive data (" + ", ".join(risky) + ") and is shown "
                             "anonymized. Fix it in the source; do not copy the placeholders into a new version.")
        return out

    # -- operations -----------------------------------------------------------------
    def list(self, org_id: str) -> list[dict[str, Any]]:
        return [s.model_dump() for s in self.backend.list(org_id)]

    def get(self, org_id: str, name: str, version: int | None = None, label: str | None = None) -> dict[str, Any]:
        check_name(name)
        if label is not None and label != "latest":
            check_label(label)
        return self._protect(self.backend.get(org_id, name, version, label))

    def history(self, org_id: str, name: str) -> list[dict[str, Any]]:
        check_name(name)
        def note(text: str | None) -> str | None:
            return self.protect_text(text) if text and self._findings(text)[0] else text

        return [{"version": v.version, "labels": v.labels, "note": note(v.note), "created_by": v.created_by,
                 "created_at": v.created_at, "hash": v.hash, "type": v.type}
                for v in self.backend.history(org_id, name)]

    def diff(self, org_id: str, name: str, from_version: int, to_version: int) -> dict[str, Any]:
        check_name(name)
        a = self.get(org_id, name, from_version)
        b = self.get(org_id, name, to_version)

        def render(p: dict) -> list[str]:
            v = p["prompt"]
            text = v if isinstance(v, str) else "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in v or [])
            return (text or "").splitlines(keepends=True)

        lines = difflib.unified_diff(render(a), render(b), f"{name}@v{from_version}", f"{name}@v{to_version}")
        config_changed = a.get("config") != b.get("config")
        return {"name": name, "from": from_version, "to": to_version, "diff": "".join(lines),
                "config_changed": config_changed, "protected": a["protected"] or b["protected"]}

    def create(self, principal, name: str, prompt: str | list[ChatMessage] | list[dict],
               config: dict[str, Any] | None = None, note: str | None = None) -> dict[str, Any]:
        check_name(name)
        if isinstance(prompt, list):
            prompt = [m if isinstance(m, ChatMessage) else ChatMessage(**m) for m in prompt]
        type_: PromptType = "text" if isinstance(prompt, str) else "chat"
        warnings = self._check_write(prompt)
        config = config or {}
        if len(json.dumps(config)) > 20_000:
            raise PromptError("config is too large", 413)
        if self._findings(json.dumps(config, ensure_ascii=False))[0]:
            raise PromptError("config contains sensitive data and was not saved", 422)
        if note and (len(note) > 500 or self._findings(note)[0]):
            raise PromptError("note is too long or contains sensitive data", 422)
        v = self.backend.create(principal.org_id, name, type_, prompt, config, note, principal.label)
        if self.audit is not None:
            self.audit.record(principal.org_id, "create", "prompt", f"{name}@v{v.version}", principal,
                              after={"name": name, "version": v.version, "hash": v.hash, "type": type_,
                                     "warnings": warnings})
        return {**self._protect(v), "draft": True,
                "notice": "Saved as a new version without labels. A human promotes it in the Cato dashboard."}

    def set_label(self, principal, name: str, version: int, label: str) -> dict[str, Any]:
        check_name(name)
        check_label(label)
        before, after = self.backend.set_label(principal.org_id, name, version, label)
        if self.audit is not None:
            self.audit.record(principal.org_id, "label", "prompt", f"{name}:{label}", principal,
                              before={"version": before} if before is not None else None, after={"version": after})
        return {"name": name, "label": label, "version": after, "previous_version": before}

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {"backend": self.backend.kind}
        if isinstance(self.backend, LangfusePromptBackend):
            u = httpx.URL(self.backend.base_url)
            out["location"] = f"{u.scheme}://{u.host}"
        return out


def backend_from_env(env: dict[str, str] | None = None, transport: httpx.BaseTransport | None = None
                     ) -> PromptBackend | None:
    env = dict(os.environ if env is None else env)
    kind = (env.get("CATO_PROMPTS") or "").strip().lower()
    if not kind:
        return None
    if kind == "local":
        return LocalPromptBackend(env.get("CATO_PROMPTS_DB", "data/prompts.db"))
    if kind == "langfuse":
        langfuse_source = env.get("CATO_SOURCE", "").lower() == "langfuse"
        pick = (lambda k: env.get(f"CATO_PROMPTS_{k}") or (env.get(f"CATO_SOURCE_{k}") if langfuse_source else None)
                or "")
        return LangfusePromptBackend(pick("URL"), pick("PUBLIC_KEY"), pick("SECRET_KEY"),
                                     float(env.get("CATO_SOURCE_TIMEOUT", "30")), transport)
    raise PromptError(f"unknown CATO_PROMPTS {kind!r}; use local or langfuse", 500)
