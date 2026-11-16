"""Cato REST API.

Security properties:
* Every /v1 endpoint requires an API key or a dashboard session token
  (``Authorization: Bearer <key>`` or ``X-API-Key``). Restore requires an
  admin API key; policy writes and account management require an admin.
* Every caller belongs to one organization. Traces, API keys, members, the
  audit log and vault namespaces are scoped to it.
* Security-relevant changes (logins, keys, members, policies, restores) are
  written to an append-only, hash-chained audit log.
* Request bodies are never logged. The access log contains method, path,
  status, latency and a request id only.
* Validation errors never echo the submitted input (FastAPI's default 422
  response would).
* Text size is capped (``CATO_MAX_CHARS``).
* Conversations (``CATO_SOURCE``) are only returned protected, behind opaque
  ids, a daily quota per key and k-anonymous statistics. Prompt versions are
  scanned before they are saved; moving a label is an admin action.
* ``CATO_MCP_HTTP=1`` serves the MCP tools at ``/mcp`` with the same keys.

Note: no ``from __future__ import annotations`` here. FastAPI must resolve
the locally defined ``User``/``Admin`` dependency types at definition time;
with string annotations they silently turn into body parameters and auth
breaks (covered by tests/test_api.py::test_endpoints_require_key).
"""


import logging
import os
import re
from contextlib import asynccontextmanager
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Annotated
from urllib.parse import urlsplit

import base64

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError

import cato
from cato.anonymize import Anonymizer, AnonymizerConfig, LeakError, restore
from cato.accounts import DEFAULT_ORG, AccountError, AccountStore, Principal
from cato.api.schemas import (
    AnonymizeRequest, ApiKeyCreate, ClassifyRequest, DetectionOut, DryRunRequest, LoginRequest, MemberCreate,
    MemberUpdate, OrganizationUpdate, PasswordChange, PolicyCreate, PolicySummary, PromptCreate, PromptLabelSet,
    ProtectRequest, ProtectResponse, RestoreRequest, ScanResponse, TextRequest,
)
from cato.audit import AuditLog
from cato.api.settings import Settings
from cato.anonymize.engine import AnonymizationResult, RestoreResult
from cato.classify import Classifier, DocumentClassification
from cato.conversations import ConversationConfig, ConversationError, ConversationService, ConversationStore
from cato.detect import Detector, DetectorConfig, load_custom_patterns
from cato.pipeline import Pipeline
from cato.policy import (
    DecisionDiff, FilePolicyStore, Policy, PolicyEngine, PolicyError, builtin_policy, diff_decisions,
)
from cato.documents import DocumentError, protect_document
from cato.gateway import Gateway, GatewayConfig, GatewayError
from cato.prompts import PromptError, PromptService, backend_from_env
from cato.sources import source_from_env
from cato.tracing import Trace, TraceStep, TraceStore, trace_from_protect
from cato.vault import FileVault, VaultError, VaultKey

log = logging.getLogger("cato.api")

# Client-supplied request ids end up in the access log.
_REQUEST_ID = re.compile(r"[\w.:-]{1,64}", re.ASCII)


class State:
    def __init__(self, settings: Settings, gateway_transport=None, source_transport=None) -> None:
        self.settings = settings
        self.accounts = AccountStore(settings.accounts_db, settings.session_hours)
        self.audit = AuditLog(settings.audit_db)
        self.traces = TraceStore(settings.trace_db, settings.trace_retention_days, retention_for=self._retention)
        if settings.bootstrap_admin and self.accounts.count_users() == 0:
            email, password = settings.bootstrap_admin
            user = self.accounts.create_user(DEFAULT_ORG, email, email.split("@")[0], password, "admin")
            self.audit.record(DEFAULT_ORG, "create", "member", user["id"], after=user,
                              actor_label="system (bootstrap)")
            log.warning("bootstrap admin created; change the password after the first login")
        custom = load_custom_patterns(settings.custom_patterns) if settings.custom_patterns else []
        self.detector = Detector(DetectorConfig(enable_ner=settings.enable_ner, custom_entities=custom))
        self.classifier = Classifier()
        self.vault = (FileVault(settings.vault_path, VaultKey.from_b64(settings.vault_key))
                      if settings.vault_key else None)
        self.policies = FilePolicyStore(settings.policy_dir)
        for builtin in ("legal-default", "support-default"):
            if builtin not in self.policies.names():
                self.policies.save(builtin_policy(builtin))
        self.gateway = Gateway(
            lambda vault: Pipeline(self.policy_for(None, None, None, None), detector=self.detector,
                                   classifier=self.classifier, vault=vault),
            GatewayConfig.from_env(settings.env), transport=gateway_transport,
        )
        env = settings.env
        self.conversation_policy = env.get("CATO_CONVERSATIONS_POLICY", "support-default")
        source = source_from_env(env, transport=source_transport)
        if source is not None or env.get("CATO_PROMPTS"):
            self.policies.effective(self.conversation_policy)  # unknown policy: fail at start, not per request
        self.conversations = None if source is None else ConversationService(
            source,
            lambda vault: Pipeline(self.policies.effective(self.conversation_policy), detector=self.detector,
                                   classifier=self.classifier, vault=vault),
            ConversationStore(settings.conversations_db), ConversationConfig.from_env(env),
            vault=self.vault, traces=self.traces, audit=self.audit,
        )
        backend = backend_from_env(env, transport=source_transport)
        self.prompts = None if backend is None else PromptService(
            backend, self.detector, self.classifier, self._protect_prompt, self.audit)

    def _protect_prompt(self, text: str) -> str | None:
        pipeline = Pipeline(self.policies.effective(self.conversation_policy), detector=self.detector,
                            classifier=self.classifier)
        return pipeline.protect(text, "external").text

    def _retention(self, org_id: str) -> int | None:
        try:
            return self.accounts.get_org(org_id)["trace_retention_days"]
        except AccountError:
            return None

    def policy_for(self, name: str | None, version: int | None, tenant: str | None, team: str | None) -> Policy:
        if name:
            return self.policies.effective(name, version)
        if tenant or team:
            return self.policies.resolve_for(tenant, team)
        return self.policies.effective(self.settings.default_policy)


def _key_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


class LoginLimiter:
    """At most ``limit`` failed logins per e-mail within ``window`` seconds."""

    def __init__(self, limit: int = 10, window: float = 900) -> None:
        self.limit, self.window = limit, window
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def blocked(self, email: str) -> bool:
        with self._lock:
            q = self._fails[email]
            while q and q[0] < time.time() - self.window:
                q.popleft()
            return len(q) >= self.limit

    def fail(self, email: str) -> None:
        with self._lock:
            self._fails[email].append(time.time())

    def reset(self, email: str) -> None:
        with self._lock:
            self._fails.pop(email, None)


def _host(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}{f':{parts.port}' if parts.port else ''}" if parts.hostname else ""


def create_app(settings: Settings | None = None, gateway_transport=None, source_transport=None) -> FastAPI:
    settings = settings or Settings.from_env()
    state = State(settings, gateway_transport, source_transport)
    mcp_holder: dict = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        import anyio
        from contextlib import AsyncExitStack

        async with AsyncExitStack() as stack:
            for key in ("server", "proxy_server"):
                if key in mcp_holder:
                    await stack.enter_async_context(mcp_holder[key].session_manager.run())
            proxy = mcp_holder.get("proxy")
            if proxy is None:
                yield
                return
            async with anyio.create_task_group() as tg:
                tg.start_soon(proxy.run)
                await proxy.wait_ready(10)
                yield
                proxy.stop()
                tg.cancel_scope.cancel()

    app = FastAPI(
        lifespan=lifespan,
        title="Cato API",
        version=cato.__version__,
        description="Privacy infrastructure for legal AI: detect, classify, anonymize and control sensitive "
                    "information before AI models process it. Responses contain offsets, never raw values.",
    )

    # -- auth -----------------------------------------------------------------
    limiter = LoginLimiter()

    def resolve(request: Request) -> Principal | None:
        return resolve_token(_key_from(request))

    def resolve_token(key: str | None) -> Principal | None:
        if not key:
            return None
        if settings.is_admin_key(key):
            return Principal("env_key", DEFAULT_ORG, "admin", "env-admin", "environment admin key")
        if settings.is_api_key(key):
            return Principal("env_key", DEFAULT_ORG, "user", "env", "environment API key")
        return state.accounts.principal(key)

    def require_key(request: Request) -> Principal:
        p = resolve(request)
        if p is None:
            raise HTTPException(status_code=401, detail="invalid or missing API key")
        return p

    def admin_keys_exist() -> bool:
        return bool(settings.admin_key_hashes) or state.accounts.has_admin_keys()

    def require_admin(request: Request) -> Principal:
        p = resolve(request)
        if p is not None and p.is_admin:
            return p
        if p is not None and p.kind != "session" and not admin_keys_exist():
            raise HTTPException(status_code=403, detail="admin endpoints are disabled (no CATO_ADMIN_KEYS)")
        raise HTTPException(status_code=403, detail="admin key required")

    def require_admin_key(request: Request) -> Principal:
        p = require_admin(request)
        if p.kind == "session":
            raise HTTPException(status_code=403, detail="restore requires an admin API key")
        return p

    def require_session(request: Request) -> Principal:
        p = require_key(request)
        if p.kind != "session":
            raise HTTPException(status_code=403, detail="dashboard session required")
        return p

    User = Annotated[Principal, Depends(require_key)]
    Admin = Annotated[Principal, Depends(require_admin)]
    AdminKey = Annotated[Principal, Depends(require_admin_key)]
    SessionUser = Annotated[Principal, Depends(require_session)]

    def scoped(p: Principal, namespace: str | None) -> str | None:
        """Vault namespaces are isolated per organization. The default org keeps plain
        names so existing vaults stay readable; other orgs get an unforgeable prefix."""
        if namespace is None:
            return None
        if "\x1f" in namespace:
            raise HTTPException(status_code=422, detail="namespace contains a control character")
        return namespace if p.org_id == DEFAULT_ORG else f"{p.org_id}\x1f{namespace}"

    # UTF-8 needs up to 4 bytes per character; the rest covers JSON framing and policy YAML.
    max_body_bytes = settings.max_chars * 4 + 512_000
    # Document uploads have their own limit plus multipart framing.
    max_upload_body_bytes = settings.max_upload_bytes + 65_536

    def check_size(text: str) -> None:
        if len(text) > settings.max_chars:
            raise HTTPException(status_code=413, detail=f"text exceeds {settings.max_chars} characters")

    # -- middleware & error handling ------------------------------------------
    @app.middleware("http")
    async def access_log(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")
        if not _REQUEST_ID.fullmatch(request_id):
            request_id = f"req_{uuid.uuid4().hex[:12]}"
        start = time.perf_counter()
        # Refuse oversized bodies before they are read and parsed (this runs
        # before authentication). Chunked uploads carry no length; cap those
        # at the reverse proxy.
        length = request.headers.get("content-length", "0")
        limit = max_upload_body_bytes if request.url.path.startswith("/v1/documents/") else max_body_bytes
        if not length.isdigit() or int(length) > limit:
            response = JSONResponse(status_code=413, content={"detail": "request body too large"})
        else:
            response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        # Never log bodies or query strings.
        log.info("%s %s %s %.1fms %s", request.method, request.url.path, response.status_code, ms, request_id)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(LeakError)
    async def leak_error(_: Request, exc: LeakError) -> JSONResponse:
        log.error("leak check failed: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "anonymization leak check failed; nothing was returned"})

    @app.exception_handler(VaultError)
    async def vault_error(_: Request, exc: VaultError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(DocumentError)
    async def document_error(_: Request, exc: DocumentError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(PolicyError)
    async def policy_error(_: Request, exc: PolicyError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ConversationError)
    async def conversation_error(_: Request, exc: ConversationError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(PromptError)
    async def prompt_error(_: Request, exc: PromptError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(AccountError)
    async def account_error(_: Request, exc: AccountError) -> JSONResponse:
        status = 404 if "not found" in str(exc) else 400
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    # -- public ----------------------------------------------------------------
    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/info", tags=["system"])
    def info(_: User) -> dict:
        ner = state.detector.scan("Herr Max Mustermann", "de").warnings
        return {
            "version": cato.__version__,
            "ner": "disabled" if not settings.enable_ner else ("unavailable" if ner else "available"),
            "vault": state.vault is not None,
            "admin_endpoints": admin_keys_exist(),
            "default_policy": settings.default_policy,
        }

    # -- core ------------------------------------------------------------------
    @app.post("/v1/scan", response_model=ScanResponse, tags=["privacy"])
    def scan(req: TextRequest, _: User) -> ScanResponse:
        check_size(req.text)
        r = state.detector.scan(req.text, req.language)
        return ScanResponse(
            language=r.language, signals=r.signals, warnings=r.warnings,
            detections=[DetectionOut(**{**d.redacted(), "category": d.category.value, "signals": list(d.signals)})
                        for d in r.detections],
        )

    @app.post("/v1/classify", response_model=DocumentClassification, tags=["privacy"])
    def classify(req: ClassifyRequest, _: User) -> DocumentClassification:
        check_size(req.text)
        r = state.detector.scan(req.text, req.language)
        return state.classifier.classify_text(req.text, r, corrections=req.corrections)

    @app.post("/v1/anonymize", response_model=AnonymizationResult, tags=["privacy"])
    def anonymize(req: AnonymizeRequest, p: User) -> AnonymizationResult:
        check_size(req.text)
        if req.namespace and state.vault is None:
            raise HTTPException(status_code=400, detail="namespace given but no vault configured (CATO_VAULT_KEY)")
        r = state.detector.scan(req.text, req.language)
        cfg = AnonymizerConfig(methods=req.methods, include_role=req.include_role)
        return Anonymizer(cfg, vault=state.vault if req.namespace else None).anonymize(
            req.text, r, namespace=scoped(p, req.namespace))

    @app.post("/v1/protect", response_model=ProtectResponse, tags=["privacy"])
    def protect(req: ProtectRequest, p: User) -> ProtectResponse:
        """Full pipeline. ``text`` is only returned when the policy allows sending it to ``destination``."""
        check_size(req.text)
        if req.namespace and state.vault is None:
            raise HTTPException(status_code=400, detail="namespace given but no vault configured (CATO_VAULT_KEY)")
        policy = state.policy_for(req.policy, req.policy_version, req.tenant, req.team)
        pipeline = Pipeline(policy, detector=state.detector, classifier=state.classifier,
                            vault=state.vault if req.namespace else None)
        t0 = time.perf_counter()
        result = pipeline.protect(req.text, req.destination, namespace=scoped(p, req.namespace),
                                  language=req.language, dry_run=req.dry_run)
        if not req.dry_run:
            state.traces.add(trace_from_protect("/v1/protect", result, round((time.perf_counter() - t0) * 1000, 1)),
                             p.org_id)
        text = None if req.dry_run else result.text
        return ProtectResponse(outcome=result.decision.outcome, allowed=result.allowed, text=text,
                               risk=result.classification.risk, decision=result.decision,
                               classification=result.classification)

    @app.post("/v1/documents/protect", tags=["documents"])
    async def protect_document_(
        p: User,
        file: UploadFile = File(..., description="PDF, DOCX or UTF-8 text"),
        destination: str = Form("external", pattern="^(external|local)$"),
        namespace: str | None = Form(None, max_length=128),
        language: str | None = Form(None, pattern="^(de|en)$"),
        policy: str | None = Form(None),
    ) -> dict:
        """Protect a document. DOCX is anonymized in place (formatting kept, properties cleared) and
        returned base64-encoded; PDF and text return anonymized text. Nothing is returned unless the
        policy allows sending. Comments, tracked changes, embedded objects and pages without a text
        layer degrade the result and put it into review."""
        data = await file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"file exceeds {settings.max_upload_bytes} bytes")
        if namespace and state.vault is None:
            raise HTTPException(status_code=400, detail="namespace given but no vault configured (CATO_VAULT_KEY)")
        pipeline = Pipeline(state.policy_for(policy, None, None, None), detector=state.detector,
                            classifier=state.classifier, vault=state.vault if namespace else None)
        t0 = time.perf_counter()
        doc = protect_document(pipeline, data, file.filename, destination, scoped(p, namespace), language,
                               max_bytes=settings.max_upload_bytes)
        r = doc.result
        trace = trace_from_protect("/v1/documents/protect", r, round((time.perf_counter() - t0) * 1000, 1))
        trace.steps.insert(1, TraceStep(name="Document parsed", detail=f"{doc.format}"
                                        + (f" · {doc.pages} pages" if doc.pages else "")
                                        + (f" · {len(doc.warnings)} warning(s)" if doc.warnings else ""),
                                        status="warning" if doc.warnings else "ok"))
        state.traces.add(trace, p.org_id)
        body = {
            "format": doc.format, "pages": doc.pages, "warnings": doc.warnings, "notes": doc.notes,
            "outcome": r.decision.outcome.value, "allowed": doc.allowed, "risk": r.classification.risk.value,
            "decision": r.decision.model_dump(mode="json"),
            "text": None, "content_base64": None, "media_type": doc.media_type,
        }
        if doc.allowed:
            if doc.format == "docx":
                body["content_base64"] = base64.b64encode(doc.content).decode()
                body["text"] = r.text
            else:
                body["text"] = doc.content.decode("utf-8")
        return body

    # -- gateway ---------------------------------------------------------------
    @app.post("/v1/chat/completions", tags=["gateway"])
    async def chat_completions(request: Request, p: User) -> JSONResponse:
        """OpenAI-compatible chat completions. Messages are protected by the active policy before they
        reach the provider; placeholders in the answer are restored. Use your Cato API key as the
        OpenAI API key and Cato's URL as base_url."""
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"error": {"message": "invalid JSON", "type":
                                                                    "invalid_request_error", "code": "invalid_json"}})
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={"error": {"message": "invalid body", "type":
                                                                    "invalid_request_error", "code": "invalid_body"}})
        total = sum(len(m.get("content")) for m in body.get("messages", []) if isinstance(m, dict)
                    and isinstance(m.get("content"), str))
        if total > settings.max_chars:
            return JSONResponse(status_code=413, content={"error": {"message": "request too large", "type":
                                                                    "invalid_request_error", "code": "too_large"}})
        try:
            data, trace = await run_in_threadpool(state.gateway.chat_completions, body)
        except GatewayError as exc:
            if exc.trace is not None:
                state.traces.add(exc.trace, p.org_id)
            headers = {"X-Cato-Trace-Id": exc.trace.id} if exc.trace else {}
            return JSONResponse(status_code=exc.status, content=exc.body(), headers=headers)
        state.traces.add(trace, p.org_id)
        return JSONResponse(content=data, headers={"X-Cato-Trace-Id": trace.id, "X-Cato-Outcome": trace.outcome or ""})

    # -- observability ---------------------------------------------------------
    @app.get("/v1/traces", response_model=list[Trace], tags=["observability"])
    def list_traces(p: User, limit: int = 50, outcome: str | None = None, route: str | None = None,
                    since: float | None = None) -> list[Trace]:
        return state.traces.list(limit, outcome, route, since, org_id=p.org_id)

    @app.get("/v1/traces/{trace_id}", response_model=Trace, tags=["observability"])
    def get_trace(trace_id: str, p: User) -> Trace:
        trace = state.traces.get(trace_id, p.org_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return trace

    @app.get("/v1/metrics", tags=["observability"])
    def metrics(p: User, hours: int = 24) -> dict:
        return state.traces.metrics(max(1, min(hours, 24 * 90)), p.org_id)

    @app.post("/v1/restore", response_model=RestoreResult, tags=["privacy"])
    def restore_(req: RestoreRequest, p: AdminKey) -> RestoreResult:
        """Resolve placeholders with the vault. Admin API key only; recorded in the audit log
        (namespace and count, never values)."""
        check_size(req.text)
        if state.vault is None:
            raise HTTPException(status_code=400, detail="no vault configured (CATO_VAULT_KEY)")
        result = restore(req.text, state.vault, scoped(p, req.namespace))
        log.warning("restore performed: %d placeholder(s) resolved", result.restored)
        state.audit.record(p.org_id, "restore", "vault", req.namespace, p,
                           after={"restored": result.restored, "unresolved": len(result.unresolved)})
        return result

    # -- policies --------------------------------------------------------------
    @app.get("/v1/policies", response_model=list[PolicySummary], tags=["policies"])
    def list_policies(_: User) -> list[PolicySummary]:
        out = []
        for name in state.policies.names():
            p = state.policies.get(name)
            out.append(PolicySummary(name=p.name, version=p.version, hash=p.content_hash, scope=p.scope.model_dump()))
        return out

    @app.get("/v1/policies/{name}", response_model=Policy, tags=["policies"])
    def get_policy(name: str, _: User, version: int | None = None, effective: bool = False) -> Policy:
        return state.policies.effective(name, version) if effective else state.policies.get(name, version)

    @app.get("/v1/policies/{name}/history", response_model=list[PolicySummary], tags=["policies"])
    def policy_history(name: str, _: User) -> list[PolicySummary]:
        return [PolicySummary(**h.model_dump()) for h in state.policies.history(name)]

    @app.post("/v1/policies", response_model=PolicySummary, status_code=201, tags=["policies"])
    def create_policy(req: PolicyCreate, p: Admin) -> PolicySummary:
        try:
            policy = Policy.from_yaml(req.yaml)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=[
                {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()])
        if p.org_id != DEFAULT_ORG:
            raise HTTPException(status_code=403, detail="policies are shared; only the default organization manages them")
        prev = state.policies.history(policy.name)[-1] if policy.name in state.policies.names() else None
        saved = state.policies.save(policy)
        log.warning("policy saved: %s %s", saved.ref, saved.content_hash)
        summary = PolicySummary(name=saved.name, version=saved.version, hash=saved.content_hash,
                                scope=saved.scope.model_dump())
        state.audit.record(p.org_id, "create" if prev is None else "update", "policy", saved.name, p,
                           before=prev.model_dump() if prev else None, after=summary.model_dump())
        return summary

    @app.post("/v1/policies/dry-run", response_model=DecisionDiff, tags=["policies"])
    def dry_run(req: DryRunRequest, _: User) -> DecisionDiff:
        """Compare a candidate policy (not saved) with an active one on a sample text."""
        check_size(req.text)
        try:
            candidate = Policy.from_yaml(req.candidate_yaml)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=[
                {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()])
        active = state.policies.effective(req.against or settings.default_policy)
        r = state.detector.scan(req.text, req.language)
        c = state.classifier.classify_text(req.text, r)
        live = PolicyEngine(active).evaluate(r.detections, c, req.destination)
        cand = PolicyEngine(candidate).evaluate(r.detections, c, req.destination, dry_run=True)
        return diff_decisions(live, cand)

    # -- auth & accounts -----------------------------------------------------------
    def me_body(p: Principal) -> dict:
        org = state.accounts.get_org(p.org_id)
        org["effective_trace_retention_days"] = org["trace_retention_days"] or settings.trace_retention_days
        user = state.accounts.get_user(p.org_id, p.id) if p.kind == "session" else None
        return {"kind": p.kind, "role": p.role, "user": user, "organization": org}

    @app.post("/v1/auth/login", tags=["accounts"])
    def login(req: LoginRequest) -> dict:
        """Exchange e-mail and password for a session token (dashboard). Failed attempts are rate
        limited per e-mail and recorded in the audit log of the user's organization."""
        email = req.email.strip().lower()
        if limiter.blocked(email):
            raise HTTPException(status_code=429, detail="too many failed logins; try again later")
        user = state.accounts.authenticate(email, req.password)
        if user is None:
            limiter.fail(email)
            known = state.accounts.user_by_email(email)
            if known is not None:
                state.audit.record(known["org_id"], "login_failed", "session", known["id"],
                                   actor_label=known["email"], actor_type="anonymous")
            raise HTTPException(status_code=401, detail="invalid e-mail or password")
        limiter.reset(email)
        token, expires = state.accounts.create_session(user["id"])
        actor = Principal("session", user["org_id"], user["role"], user["id"], user["email"])
        state.audit.record(user["org_id"], "login", "session", user["id"], actor)
        return {"token": token, "expires_at": expires, **me_body(actor)}

    @app.post("/v1/auth/logout", status_code=204, tags=["accounts"])
    def logout(request: Request, p: SessionUser) -> None:
        state.accounts.revoke_session(_key_from(request) or "")
        state.audit.record(p.org_id, "logout", "session", p.id, p)

    @app.get("/v1/auth/me", tags=["accounts"])
    def me(p: User) -> dict:
        return me_body(p)

    @app.post("/v1/auth/password", status_code=204, tags=["accounts"])
    def change_password(req: PasswordChange, request: Request, p: SessionUser) -> None:
        """Change the own password. Other sessions of the user are signed out."""
        state.accounts.set_password(p.org_id, p.id, req.current_password, req.new_password)
        state.accounts.revoke_user_sessions(p.id, keep=_key_from(request))
        state.audit.record(p.org_id, "password_change", "member", p.id, p)

    @app.get("/v1/organization", tags=["accounts"])
    def get_organization(p: User) -> dict:
        return me_body(p)["organization"]

    @app.patch("/v1/organization", tags=["accounts"])
    def update_organization(req: OrganizationUpdate, p: Admin) -> dict:
        before, after = state.accounts.update_org(p.org_id, req.name, req.trace_retention_days)
        if before != after:
            state.audit.record(p.org_id, "update", "organization", p.org_id, p, before=before, after=after)
        return me_body(p)["organization"]

    @app.get("/v1/members", tags=["accounts"])
    def list_members(p: User) -> list[dict]:
        return state.accounts.list_users(p.org_id)

    @app.post("/v1/members", status_code=201, tags=["accounts"])
    def create_member(req: MemberCreate, p: Admin) -> dict:
        user = state.accounts.create_user(p.org_id, req.email, req.name, req.password, req.role)
        state.audit.record(p.org_id, "create", "member", user["id"], p, after=user)
        return user

    @app.patch("/v1/members/{user_id}", tags=["accounts"])
    def update_member(user_id: str, req: MemberUpdate, p: Admin) -> dict:
        before, after = state.accounts.update_user(p.org_id, user_id, p.id, req.role, req.disabled, req.name)
        if before != after:
            state.audit.record(p.org_id, "update", "member", user_id, p, before=before, after=after)
        return after

    @app.get("/v1/api-keys", tags=["accounts"])
    def list_api_keys(p: User) -> list[dict]:
        return state.accounts.list_api_keys(p.org_id)

    @app.post("/v1/api-keys", status_code=201, tags=["accounts"])
    def create_api_key(req: ApiKeyCreate, p: Admin) -> dict:
        """Create an API key. The key is returned once and stored as a hash only."""
        key, meta = state.accounts.create_api_key(p.org_id, req.name, req.role, p.id)
        state.audit.record(p.org_id, "create", "api_key", meta["id"], p, after=meta)
        return {**meta, "key": key}

    @app.delete("/v1/api-keys/{key_id}", tags=["accounts"])
    def revoke_api_key(key_id: str, p: Admin) -> dict:
        before, after = state.accounts.revoke_api_key(p.org_id, key_id)
        state.audit.record(p.org_id, "revoke", "api_key", key_id, p, before=before, after=after)
        return after

    # -- audit log -------------------------------------------------------------------
    @app.get("/v1/audit-logs", tags=["audit"])
    def list_audit_logs(p: Admin, limit: int = 50, before: int | None = None, action: str | None = None,
                        resource_type: str | None = None, actor_id: str | None = None) -> dict:
        """Newest first. Page with ``before`` = ``next_before`` of the previous page."""
        rows = state.audit.list(p.org_id, limit, before, action, resource_type, actor_id)
        return {"data": rows, "next_before": rows[-1]["seq"] if len(rows) == min(max(limit, 1), 200) else None,
                **state.audit.facets(p.org_id)}

    @app.get("/v1/audit-logs/verify", tags=["audit"])
    def verify_audit_logs(p: Admin) -> dict:
        return state.audit.verify(p.org_id)

    @app.get("/v1/audit-logs/{entry_id}", tags=["audit"])
    def get_audit_log(entry_id: str, p: Admin) -> dict:
        entry = state.audit.get(p.org_id, entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="audit log entry not found")
        return entry

    # -- conversations -----------------------------------------------------------------
    def conversations() -> ConversationService:
        if state.conversations is None:
            raise HTTPException(status_code=404, detail="conversation access is not configured (CATO_SOURCE)")
        return state.conversations

    def prompts() -> PromptService:
        if state.prompts is None:
            raise HTTPException(status_code=404, detail="prompt management is not configured (CATO_PROMPTS)")
        return state.prompts

    @app.get("/v1/sources", tags=["conversations"])
    def sources(_: User) -> dict:
        """What is connected, without credentials (adapter type and host only)."""
        return {
            "conversations": state.conversations.describe() if state.conversations else None,
            "conversation_policy": state.conversation_policy if state.conversations else None,
            "prompts": state.prompts.describe() if state.prompts else None,
            "mcp_http": settings.mcp_http,
        }

    @app.get("/v1/conversations", tags=["conversations"])
    def list_conversations(p: User, since: float | None = None, until: float | None = None, tag: str | None = None,
                           limit: int = 50, cursor: str | None = None) -> dict:
        """Opaque ids and allow-listed metadata. No content."""
        return conversations().list(p, since, until, tag, limit, cursor)

    @app.get("/v1/conversations/stats", tags=["conversations"])
    def conversation_stats(p: User, since: float | None = None, until: float | None = None,
                           group_by: str = "day") -> dict:
        return conversations().stats(p, since, until, group_by)

    @app.get("/v1/conversations/quota", tags=["conversations"])
    def conversation_quota(p: User) -> dict:
        return conversations().quota(p)

    @app.get("/v1/conversations/{conversation_id}", tags=["conversations"])
    def get_conversation(conversation_id: str, p: User) -> dict:
        """Protected messages. Counts against the daily quota; traced and audited."""
        return conversations().get(p, conversation_id)

    # -- prompts ---------------------------------------------------------------------------
    @app.get("/v1/prompts", tags=["prompts"])
    def list_prompts(p: User) -> list[dict]:
        return prompts().list(p.org_id)

    @app.post("/v1/prompts", status_code=201, tags=["prompts"])
    def create_prompt(req: PromptCreate, p: User) -> dict:
        """New version without labels. Rejected if it contains sensitive data or Cato placeholders."""
        body = req.prompt if isinstance(req.prompt, str) else [m.model_dump() for m in req.prompt]
        return prompts().create(p, req.name, body, req.config, req.note)

    @app.get("/v1/prompts/{name}", tags=["prompts"])
    def get_prompt(name: str, p: User, version: int | None = None, label: str | None = None) -> dict:
        return prompts().get(p.org_id, name, version, label)

    @app.get("/v1/prompts/{name}/history", tags=["prompts"])
    def prompt_history(name: str, p: User) -> list[dict]:
        return prompts().history(p.org_id, name)

    @app.get("/v1/prompts/{name}/diff", tags=["prompts"])
    def prompt_diff(name: str, p: User, from_version: int, to_version: int) -> dict:
        return prompts().diff(p.org_id, name, from_version, to_version)

    @app.post("/v1/prompts/{name}/labels", tags=["prompts"])
    def set_prompt_label(name: str, req: PromptLabelSet, p: Admin) -> dict:
        """Move a label (e.g. production) to a version. Admin only; audited with before/after."""
        return prompts().set_label(p, name, req.version, req.label)

    # -- MCP over HTTP -------------------------------------------------------------------------
    if settings.mcp_http:
        from starlette.routing import Route

        from cato.mcp import CatoTools, MCPConfig, http_server

        mcp_env = {k: v for k, v in settings.env.items() if k.startswith("CATO_MCP_")}
        if settings.vault_key:
            mcp_env |= {"CATO_VAULT_KEY": settings.vault_key, "CATO_VAULT_PATH": str(settings.vault_path)}
        tools = CatoTools(MCPConfig.from_env(mcp_env), detector=state.detector,
                          conversations=state.conversations, prompts=state.prompts)
        hosts = [h.strip() for h in settings.env.get("CATO_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
        server, endpoint = http_server(tools, lambda token: resolve_token(token), hosts)
        mcp_holder["server"] = server
        app.router.routes.append(Route("/mcp", endpoint=endpoint))

    # -- MCP proxy (other MCP servers behind Cato) -----------------------------------------------
    if settings.env.get("CATO_PROXY_CONFIG"):
        from starlette.routing import Route

        from cato.proxy import CatoProxy, ProxyConfig, http_proxy

        proxy = CatoProxy(ProxyConfig.load(settings.env["CATO_PROXY_CONFIG"], {**os.environ, **settings.env}),
                          detector=state.detector, traces=state.traces, audit=state.audit,
                          vault=state.vault)
        hosts = [h.strip() for h in settings.env.get("CATO_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
        proxy_server, proxy_endpoint = http_proxy(proxy, lambda token: resolve_token(token), hosts)
        mcp_holder["proxy"], mcp_holder["proxy_server"] = proxy, proxy_server
        app.router.routes.append(Route("/proxy/mcp", endpoint=proxy_endpoint))

    @app.get("/v1/proxy", tags=["mcp"])
    def proxy_status(_: User) -> dict:
        """Upstreams of the MCP proxy: connection, mode, policy, tool counts. 404 if not configured."""
        if "proxy" not in mcp_holder:
            raise HTTPException(status_code=404, detail="MCP proxy is not configured (CATO_PROXY_CONFIG)")
        p = mcp_holder["proxy"]
        return {"path": "/proxy/mcp", "destination": p.config.destination, "upstreams": p.status(),
                "tools": [t.name for t in p.list_tools()]}

    # -- gateway status --------------------------------------------------------------
    @app.get("/v1/gateway", tags=["gateway"])
    def gateway_status(_: User) -> dict:
        """Gateway configuration without credentials (host only, never keys or paths)."""
        cfg = state.gateway.config

        def up(u) -> dict | None:
            return None if u is None else {"host": _host(u.base_url), "provider": u.provider,
                                           "model": u.model, "authenticated": bool(u.api_key)}

        return {"external": up(cfg.external), "local": up(cfg.local), "restore_responses": cfg.restore_responses,
                "timeout_s": cfg.timeout, "streaming": False, "endpoint": "/v1/chat/completions",
                "default_policy": settings.default_policy}

    return app


def run() -> None:  # pragma: no cover
    import os

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host=os.environ.get("CATO_HOST", "127.0.0.1"),
                port=int(os.environ.get("CATO_PORT", "8080")), access_log=False)
