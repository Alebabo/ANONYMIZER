"""Conversation sources: read-only adapters for customer chat history.

A source returns raw conversations. Nothing in this module protects data:
the :mod:`anonymizer.conversations` service runs every message through the
pipeline before anything leaves Anonymizer. Sources never write.

Adapters (``ANONYMIZER_SOURCE``):

* ``jsonl``    one conversation per line (exports, tests, demo)
* ``http``     a generic two-endpoint read-only contract (docs/conversations.md)
* ``langfuse`` Langfuse sessions and traces via the public API

All adapters raise :class:`SourceError` with a message that never contains
conversation content or credentials.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

Role = Literal["user", "assistant", "system", "tool"]


class SourceError(RuntimeError):
    pass


class Message(BaseModel):
    role: Role
    content: str
    created_at: float | None = None
    # Optional short labels per message (e.g. which agent or workflow answered). Anonymizer passes them on
    # only if they contain nothing detectable, like tags.
    agent: str | None = None
    action: str | None = None
    subtopic: str | None = None


class ConversationHead(BaseModel):
    """Listing entry as the source returns it. ``id`` is the source id and never leaves Anonymizer."""

    id: str
    created_at: float
    message_count: int | None = None
    language: str | None = None
    channel: str | None = None
    tags: list[str] = Field(default_factory=list)
    prompt: str | None = None  # e.g. "support-bot@12" or "support-bot"
    prompt_version: int | None = None


class Conversation(ConversationHead):
    messages: list[Message] = Field(default_factory=list)


class Page(BaseModel):
    data: list[ConversationHead]
    next_cursor: str | None = None


class ConversationSource(Protocol):
    kind: str

    def list(self, since: float | None = None, until: float | None = None, limit: int = 50,
             cursor: str | None = None, tag: str | None = None) -> Page: ...

    def get(self, source_id: str) -> Conversation: ...

    def describe(self) -> dict[str, Any]: ...


def _host(url: str) -> str:
    u = httpx.URL(url)
    return f"{u.scheme}://{u.host}{f':{u.port}' if u.port else ''}"


def _in_range(created_at: float, since: float | None, until: float | None) -> bool:
    return (since is None or created_at >= since) and (until is None or created_at < until)


# -- jsonl ---------------------------------------------------------------------

class JsonlSource:
    """One JSON object per line in the :class:`Conversation` shape. Read on every call, so an
    updated export is picked up without a restart. Meant for exports and demos, not millions of rows."""

    kind = "jsonl"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise SourceError("ANONYMIZER_SOURCE_PATH does not point to a file")

    def _all(self) -> list[Conversation]:
        out: list[Conversation] = []
        with self.path.open(encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    out.append(Conversation.model_validate(json.loads(line)))
                except (ValueError, ValidationError):
                    # Never echo the line: it is customer content.
                    raise SourceError(f"line {n} of the JSONL source is not a valid conversation") from None
        return sorted(out, key=lambda c: c.created_at, reverse=True)

    def list(self, since=None, until=None, limit=50, cursor=None, tag=None) -> Page:
        rows = [c for c in self._all() if _in_range(c.created_at, since, until) and (tag is None or tag in c.tags)]
        start = int(cursor) if cursor and cursor.isdigit() else 0
        chunk = rows[start:start + limit]
        heads = [ConversationHead(**{**c.model_dump(exclude={"messages"}),
                                     "message_count": c.message_count or len(c.messages)}) for c in chunk]
        return Page(data=heads, next_cursor=str(start + limit) if start + limit < len(rows) else None)

    def get(self, source_id: str) -> Conversation:
        for c in self._all():
            if c.id == source_id:
                return c
        raise SourceError("conversation not found in source")

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "location": self.path.name}


# -- http contract ---------------------------------------------------------------

class HttpSource:
    """Generic read-only contract::

        GET {base}/conversations?since=&until=&limit=&cursor=&tag=  -> {"data": [head...], "next_cursor": ...}
        GET {base}/conversations/{id}                               -> conversation

    Authentication: a bearer key (``api_key``) or HTTP basic (``username`` + ``password``), not both.
    """

    kind = "http"

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, username: str | None = None,
                 password: str | None = None) -> None:
        if not base_url:
            raise SourceError("ANONYMIZER_SOURCE_URL is required for the http source")
        if bool(username) != bool(password):
            raise SourceError("basic auth needs both ANONYMIZER_SOURCE_USER and ANONYMIZER_SOURCE_PASSWORD")
        if api_key and username:
            raise SourceError("set either ANONYMIZER_SOURCE_KEY or ANONYMIZER_SOURCE_USER/ANONYMIZER_SOURCE_PASSWORD, not both")
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        auth = httpx.BasicAuth(username, password) if username and password else None
        self.client = httpx.Client(base_url=self.base_url, headers=headers, auth=auth, timeout=timeout,
                                   transport=transport)

    def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            r = self.client.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        except httpx.HTTPError as exc:
            raise SourceError(f"source unreachable ({type(exc).__name__})") from None
        if r.status_code == 404:
            raise SourceError("conversation not found in source")
        if r.status_code >= 400:
            raise SourceError(f"source returned HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise SourceError("source returned invalid JSON") from None

    def list(self, since=None, until=None, limit=50, cursor=None, tag=None) -> Page:
        body = self._get("/conversations", {"since": since, "until": until, "limit": limit, "cursor": cursor,
                                            "tag": tag})
        try:
            return Page.model_validate(body)
        except ValidationError:
            raise SourceError("source listing does not match the contract") from None

    def get(self, source_id: str) -> Conversation:
        body = self._get(f"/conversations/{_quote(source_id)}")
        try:
            return Conversation.model_validate(body)
        except ValidationError:
            raise SourceError("source conversation does not match the contract") from None

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "location": _host(self.base_url)}


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


# -- langfuse --------------------------------------------------------------------

_TEXT_KEYS = ("content", "text", "message", "query", "question", "input", "output", "answer", "response",
              "completion")


def _text(value: Any, prefer_role: str | None = None) -> str | None:
    """Best-effort extraction of the human-readable text from a Langfuse trace input/output.

    Chat histories (lists of ``{role, content}``) yield the last message of ``prefer_role``, because
    most applications log the full history on every turn. Anything unrecognised becomes compact JSON:
    it still goes through detection, so this errs on the side of showing more structure, not less
    protection."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        msgs = [m for m in value if isinstance(m, dict) and "role" in m]
        if msgs:
            pick = [m for m in msgs if m.get("role") == prefer_role] if prefer_role else msgs
            return _text((pick or msgs)[-1].get("content"))
        parts = [p.get("text") for p in value if isinstance(p, dict) and isinstance(p.get("text"), str)]
        if parts:
            return "\n".join(parts)
    if isinstance(value, dict):
        if "messages" in value:
            return _text(value["messages"], prefer_role)
        if "choices" in value and isinstance(value["choices"], list) and value["choices"]:
            return _text(value["choices"][0].get("message", {}).get("content"))
        for key in _TEXT_KEYS:
            if key in value:
                found = _text(value[key], prefer_role)
                if found:
                    return found
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:20_000]


def _ts(value: Any) -> float:
    from datetime import datetime

    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _iso(ts: float | None) -> str | None:
    from datetime import datetime, timezone

    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


class LangfuseSource:
    """Langfuse sessions as conversations, their traces as turns (input → user, output → assistant).

    Uses ``GET /api/public/sessions`` and ``GET /api/public/sessions/{id}`` with HTTP basic auth
    (public key / secret key). The prompt that served a trace is read from trace metadata
    (``prompt``/``prompt_name`` and ``prompt_version``) when the application sets it."""

    kind = "langfuse"

    def __init__(self, base_url: str, public_key: str, secret_key: str, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not (base_url and public_key and secret_key):
            raise SourceError("the langfuse source needs ANONYMIZER_SOURCE_URL, ANONYMIZER_SOURCE_PUBLIC_KEY and "
                              "ANONYMIZER_SOURCE_SECRET_KEY")
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, auth=(public_key, secret_key), timeout=timeout,
                                   transport=transport)

    def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            r = self.client.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        except httpx.HTTPError as exc:
            raise SourceError(f"Langfuse unreachable ({type(exc).__name__})") from None
        if r.status_code == 404:
            raise SourceError("conversation not found in source")
        if r.status_code >= 400:
            raise SourceError(f"Langfuse returned HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise SourceError("Langfuse returned invalid JSON") from None

    def list(self, since=None, until=None, limit=50, cursor=None, tag=None) -> Page:
        page = int(cursor) if cursor and cursor.isdigit() else 1
        body = self._get("/api/public/sessions", {"page": page, "limit": min(limit, 100),
                                                  "fromTimestamp": _iso(since), "toTimestamp": _iso(until)})
        data = body.get("data", []) if isinstance(body, dict) else []
        heads = [ConversationHead(id=str(s["id"]), created_at=_ts(s.get("createdAt")),
                                  tags=[str(t) for t in s.get("tags") or []])
                 for s in data if isinstance(s, dict) and s.get("id")]
        if tag is not None:  # sessions carry no tags in all Langfuse versions; filter what we have
            heads = [h for h in heads if tag in h.tags]
        meta = body.get("meta", {}) if isinstance(body, dict) else {}
        more = meta.get("totalPages") is not None and page < int(meta["totalPages"])
        return Page(data=heads, next_cursor=str(page + 1) if more else None)

    def get(self, source_id: str) -> Conversation:
        body = self._get(f"/api/public/sessions/{_quote(source_id)}")
        if not isinstance(body, dict):
            raise SourceError("Langfuse session has an unexpected shape")
        traces = sorted((t for t in body.get("traces") or [] if isinstance(t, dict)),
                        key=lambda t: _ts(t.get("timestamp")))
        messages: list[Message] = []
        tags: set[str] = set()
        prompt, prompt_version = None, None
        for t in traces:
            ts = _ts(t.get("timestamp"))
            if (inp := _text(t.get("input"), "user")) is not None:
                messages.append(Message(role="user", content=inp, created_at=ts))
            if (out := _text(t.get("output"), "assistant")) is not None:
                messages.append(Message(role="assistant", content=out, created_at=ts))
            tags.update(str(x) for x in t.get("tags") or [])
            meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
            prompt = meta.get("prompt_name") or meta.get("prompt") or prompt
            if isinstance(meta.get("prompt_version"), int):
                prompt_version = meta["prompt_version"]
        return Conversation(id=str(body.get("id", source_id)), created_at=_ts(body.get("createdAt")),
                            message_count=len(messages), tags=sorted(tags),
                            prompt=str(prompt) if prompt else None, prompt_version=prompt_version,
                            messages=messages)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "location": _host(self.base_url)}


# -- factory ---------------------------------------------------------------------

def source_from_env(env: dict[str, str] | None = None,
                    transport: httpx.BaseTransport | None = None) -> ConversationSource | None:
    """Build the configured source, or ``None`` when ``ANONYMIZER_SOURCE`` is unset. Unknown values fail."""
    env = dict(os.environ if env is None else env)
    kind = (env.get("ANONYMIZER_SOURCE") or "").strip().lower()
    if not kind:
        return None
    timeout = float(env.get("ANONYMIZER_SOURCE_TIMEOUT", "30"))
    if kind == "jsonl":
        return JsonlSource(env.get("ANONYMIZER_SOURCE_PATH", ""))
    if kind == "http":
        return HttpSource(env.get("ANONYMIZER_SOURCE_URL", ""), env.get("ANONYMIZER_SOURCE_KEY") or None, timeout, transport,
                          username=env.get("ANONYMIZER_SOURCE_USER") or None,
                          password=env.get("ANONYMIZER_SOURCE_PASSWORD") or None)
    if kind == "langfuse":
        return LangfuseSource(env.get("ANONYMIZER_SOURCE_URL", ""), env.get("ANONYMIZER_SOURCE_PUBLIC_KEY", ""),
                              env.get("ANONYMIZER_SOURCE_SECRET_KEY", ""), timeout, transport)
    if kind == "python":
        return _plugin_source(env.get("ANONYMIZER_SOURCE_CLASS", ""), env, timeout, transport)
    raise SourceError(f"unknown ANONYMIZER_SOURCE {kind!r}; use jsonl, http, langfuse or python")


def _plugin_source(spec: str, env: dict[str, str], timeout: float,
                   transport: httpx.BaseTransport | None) -> ConversationSource:
    """Load a source class from a local file: ``ANONYMIZER_SOURCE_CLASS=path/to/file.py:ClassName``.

    For company-specific adapters that do not belong in this repository (keep them in ``local/``).
    The class is called as ``Class(env=env, timeout=timeout, transport=transport)`` and implements
    :class:`ConversationSource`; an optional ``kpis(since, until) -> dict`` feeds ``get_kpis``.
    """
    import importlib.util

    path, _, name = spec.rpartition(":")
    if not path or not name or not Path(path).is_file():
        raise SourceError("ANONYMIZER_SOURCE_CLASS must be <existing file.py>:<ClassName>")
    mod_spec = importlib.util.spec_from_file_location(f"anonymizer_source_{Path(path).stem}", path)
    if mod_spec is None or mod_spec.loader is None:
        raise SourceError("ANONYMIZER_SOURCE_CLASS file cannot be loaded")
    module = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(module)
    cls = getattr(module, name, None)
    if cls is None:
        raise SourceError(f"ANONYMIZER_SOURCE_CLASS: no class {name!r} in the file")
    return cls(env=env, timeout=timeout, transport=transport)


__all__ = ["Conversation", "ConversationHead", "ConversationSource", "HttpSource", "JsonlSource",
           "LangfuseSource", "Message", "Page", "SourceError", "source_from_env"]
