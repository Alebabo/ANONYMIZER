"""OpenAI-compatible privacy gateway (``POST /v1/chat/completions``).

Existing applications only change ``base_url`` (and use a Anonymizer API key);
Anonymizer protects every message before it reaches the provider and restores
placeholders in the answer.

Flow per request
1. Collect text from ``messages[].content`` (string or text parts) and
   ``tool_calls[].function.arguments``. Non-text parts (images, audio) are
   rejected: Anonymizer cannot inspect them.
2. Protect each text with the active policy. A per-request in-memory vault
   keeps placeholders consistent across all messages of the request and is
   discarded afterwards (nothing about the mapping is persisted).
3. Outcome = most restrictive across messages.
   * allow       -> forward to the external upstream
   * local_only  -> forward to the local upstream if configured
                    (re-evaluated for destination "local"), else refuse
   * review/block-> refuse with an OpenAI-style error (HTTP 403)
4. Restore placeholders in the response (configurable), record a trace.

Streaming is not supported yet (placeholders can be split across chunks).
"""

from __future__ import annotations

import copy
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from anonymizer.anonymize import restore
from anonymizer.pipeline import Pipeline
from anonymizer.tracing import Trace, TraceStep, merge_traces, trace_from_protect
from anonymizer.vault import InMemoryVault, VaultKey

NAMESPACE = "request"
_ORDER = ["allow", "review", "local_only", "block"]


@dataclass
class Upstream:
    base_url: str
    api_key: str | None = None
    provider: str = "openai"
    model: str | None = None  # override (e.g. local model name)

    def url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


@dataclass
class GatewayConfig:
    external: Upstream | None = None
    local: Upstream | None = None
    restore_responses: bool = True
    timeout: float = 120.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "GatewayConfig":
        env = dict(os.environ if env is None else env)
        ext = local = None
        if env.get("ANONYMIZER_UPSTREAM_URL"):
            ext = Upstream(env["ANONYMIZER_UPSTREAM_URL"], env.get("ANONYMIZER_UPSTREAM_KEY") or None,
                           env.get("ANONYMIZER_UPSTREAM_PROVIDER", "openai"))
        if env.get("ANONYMIZER_LOCAL_UPSTREAM_URL"):
            local = Upstream(env["ANONYMIZER_LOCAL_UPSTREAM_URL"], env.get("ANONYMIZER_LOCAL_UPSTREAM_KEY") or None,
                             env.get("ANONYMIZER_LOCAL_UPSTREAM_PROVIDER", "local"), env.get("ANONYMIZER_LOCAL_MODEL") or None)
        return cls(ext, local, env.get("ANONYMIZER_GATEWAY_RESTORE", "1") != "0",
                   float(env.get("ANONYMIZER_GATEWAY_TIMEOUT", "120")))


class GatewayError(Exception):
    def __init__(self, status: int, message: str, code: str, trace: Trace | None = None,
                 type_: str = "anonymizer_error") -> None:
        super().__init__(message)
        self.status, self.message, self.code, self.trace, self.type = status, message, code, trace, type_

    def body(self) -> dict[str, Any]:
        err = {"message": self.message, "type": self.type, "code": self.code, "param": None}
        if self.trace is not None:
            err["anonymizer_trace_id"] = self.trace.id
        return {"error": err}


# ---------------------------------------------------------------------------
def _text_slots(body: dict[str, Any]) -> list[tuple[list, Any, str]]:
    """(container, key, text) for every protectable string in the messages."""
    slots: list[tuple[list, Any, str]] = []
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise GatewayError(400, "messages must be a non-empty list", "invalid_request", type_="invalid_request_error")
    for msg in messages:
        if not isinstance(msg, dict):
            raise GatewayError(400, "invalid message", "invalid_request", type_="invalid_request_error")
        content = msg.get("content")
        if isinstance(content, str):
            if content.strip():
                slots.append((msg, "content", content))
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "text":
                    raise GatewayError(400, "only text content is supported; Anonymizer cannot inspect images or audio",
                                       "unsupported_content", type_="invalid_request_error")
                if part.get("text", "").strip():
                    slots.append((part, "text", part["text"]))
        elif content is not None:
            raise GatewayError(400, "invalid message content", "invalid_request", type_="invalid_request_error")
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            if isinstance(fn.get("arguments"), str) and fn["arguments"].strip():
                slots.append((fn, "arguments", fn["arguments"]))
    return slots


class Gateway:
    def __init__(self, pipeline_factory, config: GatewayConfig, transport: httpx.BaseTransport | None = None) -> None:
        """``pipeline_factory(vault) -> Pipeline`` builds a pipeline bound to the request vault."""
        self.pipeline_factory = pipeline_factory
        self.config = config
        self.transport = transport

    def _protect_all(self, body: dict[str, Any], destination: str):
        vault = InMemoryVault(VaultKey.generate())
        pipeline: Pipeline = self.pipeline_factory(vault)
        work = copy.deepcopy(body)
        slots = _text_slots(work)
        results = [pipeline.protect(text, destination, namespace=NAMESPACE) for _, _, text in slots]
        return work, slots, results, vault

    def chat_completions(self, body: dict[str, Any]) -> tuple[dict[str, Any], Trace]:
        start = time.perf_counter()
        if body.get("stream"):
            raise GatewayError(400, "stream=true is not supported by Anonymizer yet", "stream_not_supported",
                               type_="invalid_request_error")
        if self.config.external is None and self.config.local is None:
            raise GatewayError(503, "no upstream provider configured", "no_upstream")

        destination = "external" if self.config.external else "local"
        work, slots, results, vault = self._protect_all(body, destination)
        outcome = max((r.decision.outcome.value for r in results), key=_ORDER.index, default="allow")
        upstream = self.config.external if destination == "external" else self.config.local
        routed_local = False
        if outcome == "local_only" and destination == "external" and self.config.local is not None:
            destination, upstream, routed_local = "local", self.config.local, True
            work, slots, results, vault = self._protect_all(body, destination)
            outcome = max((r.decision.outcome.value for r in results), key=_ORDER.index, default="allow")

        parts = [trace_from_protect("/v1/chat/completions", r, original=text, label=f"message {i + 1}")
                 for i, ((_, _, text), r) in enumerate(zip(slots, results))]
        model = upstream.model or body.get("model")
        trace = merge_traces("/v1/chat/completions", parts, provider=upstream.provider, model=model)
        trace.destination = destination
        trace.steps = [
            TraceStep(name="Request received", detail=f"POST /v1/chat/completions · {len(slots)} text part(s)"),
            TraceStep(name="Privacy detection", detail=f"{sum(trace.entity_counts.values())} entities detected",
                      status="warning" if trace.warnings else "ok"),
            TraceStep(name="Classification", detail=f"risk {trace.risk}",
                      status="warning" if trace.needs_review else "ok"),
            TraceStep(name="Policy evaluation", detail=f"{trace.policy} → {outcome}"
                      + (" (routed to local model)" if routed_local else ""),
                      status="ok" if outcome == "allow" else "blocked"),
        ]

        if outcome != "allow":
            trace.status = 403
            trace.latency_ms = round((time.perf_counter() - start) * 1000, 1)
            reasons = sorted({r for res in results for r in res.decision.reasons if res.decision.outcome.value != "allow"})
            msg = {"local_only": "content may only be processed by a local model and no local upstream is configured",
                   "review": "content requires human review before it may be sent",
                   "block": "content must not be sent to a model"}[outcome]
            raise GatewayError(403, f"Anonymizer policy: {msg}. Reasons: {'; '.join(reasons)}", outcome, trace,
                               type_="anonymizer_policy_violation")

        for (container, key, _), result in zip(slots, results):
            container[key] = result.text
        trace.steps.append(TraceStep(name="Anonymization", detail=f"{trace.transformations} transformations applied"))
        if upstream.model:
            work["model"] = upstream.model

        headers = {"Content-Type": "application/json"}
        if upstream.api_key:
            headers["Authorization"] = f"Bearer {upstream.api_key}"
        try:
            with httpx.Client(timeout=self.config.timeout, transport=self.transport) as client:
                resp = client.post(upstream.url(), json=work, headers=headers)
        except httpx.HTTPError as exc:
            trace.status, trace.error = 502, type(exc).__name__
            trace.steps.append(TraceStep(name="Provider request", detail=f"{upstream.provider}: {type(exc).__name__}",
                                         status="error"))
            trace.latency_ms = round((time.perf_counter() - start) * 1000, 1)
            raise GatewayError(502, "upstream provider unreachable", "upstream_unreachable", trace) from exc

        trace.steps.append(TraceStep(name="Provider request", detail=f"{upstream.provider} · {model} · HTTP {resp.status_code}",
                                     status="ok" if resp.is_success else "error"))
        try:
            data = resp.json()
        except ValueError:
            data = {"error": {"message": "invalid upstream response", "type": "upstream_error"}}
        if not resp.is_success:
            trace.status, trace.error = resp.status_code, "upstream_error"
            trace.latency_ms = round((time.perf_counter() - start) * 1000, 1)
            raise GatewayError(resp.status_code, "upstream provider returned an error",
                               str((data.get("error") or {}).get("code") or "upstream_error"), trace,
                               type_="upstream_error")

        restored = unresolved = 0
        if self.config.restore_responses:
            for choice in data.get("choices") or []:
                msg = choice.get("message") or {}
                if isinstance(msg.get("content"), str):
                    r = restore(msg["content"], vault, NAMESPACE)
                    msg["content"], restored, unresolved = r.text, restored + r.restored, unresolved + len(r.unresolved)
                for call in msg.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    if isinstance(fn.get("arguments"), str):
                        r = restore(fn["arguments"], vault, NAMESPACE)
                        fn["arguments"], restored = r.text, restored + r.restored
            trace.steps.append(TraceStep(name="Response restore",
                                         detail=f"{restored} placeholder(s) restored, {unresolved} unknown",
                                         status="warning" if unresolved else "ok"))
        trace.latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return data, trace
