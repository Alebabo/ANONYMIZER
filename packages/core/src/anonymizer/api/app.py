"""OpenAnonymizer REST API.

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
* Text size is capped (``ANONYMIZER_MAX_CHARS``).
* ``ANONYMIZER_MCP_HTTP=1`` serves the MCP tools at ``/mcp`` with the same keys.

Note: no ``from __future__ import annotations`` here. FastAPI must resolve
the locally defined ``User``/``Admin`` dependency types at definition time;
with string annotations they silently turn into body parameters and auth
breaks (covered by tests/test_api.py::test_endpoints_require_key).
"""


import logging
import re
from contextlib import asynccontextmanager
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Annotated

import base64

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

import anonymizer
from anonymizer.anonymize import OpenAnonymizer, AnonymizerConfig, LeakError, restore
from anonymizer.accounts import DEFAULT_ORG, AccountError, AccountStore, Principal
from anonymizer.api.schemas import (
    AnonymizeRequest, ApiKeyCreate, ClassifyRequest, DetectionOut, DryRunRequest, DryRunResult, LoginRequest, PolicyTestRequest, PolicyTestResult, MemberCreate,
    MemberUpdate, OrganizationUpdate, PasswordChange, PolicyCreate, PolicySummary,
    FeedbackCreate, PlaygroundColumns, PlaygroundQuery, PlaygroundUpload, ProtectRequest, ProtectResponse, RestoreRequest, ScanResponse, TextRequest,
)
from anonymizer.audit import AuditLog
from anonymizer.api.settings import Settings
from anonymizer.anonymize.engine import AnonymizationResult, RestoreResult
from anonymizer.classify import Classifier, DocumentClassification
from anonymizer.detect import Detector, DetectorConfig, load_custom_patterns
from anonymizer.feedback import FeedbackError, FeedbackStore
from anonymizer.pipeline import Pipeline, ProtectResult
from anonymizer.policy.edit import apply_changes
from anonymizer.playground import MAX_BYTES as PLAYGROUND_MAX_BYTES
from anonymizer.playground import PlaygroundError, PlaygroundService, PlaygroundStore
from anonymizer.policy import (
    FilePolicyStore, Policy, PolicyEngine, PolicyError, builtin_policy, diff_decisions,
)
from anonymizer.documents import DocumentError, protect_document
from anonymizer.tracing import Trace, TraceStep, TraceStore, trace_from_protect, trace_from_scan
from anonymizer.vault import FileVault, InMemoryVault, VaultError, VaultKey

log = logging.getLogger("anonymizer.api")

# Client-supplied request ids end up in the access log.
_REQUEST_ID = re.compile(r"[\w.:-]{1,64}", re.ASCII)


class State:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.accounts = AccountStore(settings.accounts_db, settings.session_hours)
        self.audit = AuditLog(settings.audit_db)
        self.traces = TraceStore(settings.trace_db, settings.trace_retention_days, retention_for=self._retention,
                                 store_content=settings.trace_content)
        if settings.bootstrap_admin and self.accounts.count_users() == 0:
            email, password = settings.bootstrap_admin
            user = self.accounts.create_user(DEFAULT_ORG, email, email.split("@")[0], password, "admin")
            self.audit.record(DEFAULT_ORG, "create", "member", user["id"], after=user,
                              actor_label="system (bootstrap)")
            log.warning("bootstrap admin created; change the password after the first login")
        custom = load_custom_patterns(settings.custom_patterns) if settings.custom_patterns else []
        self.detector = Detector(DetectorConfig(enable_ner=settings.enable_ner, custom_entities=custom,
                                                keep_terms=settings.keep_terms))
        self.classifier = Classifier()
        self.vault = (FileVault(settings.vault_path, VaultKey.from_b64(settings.vault_key))
                      if settings.vault_key else None)
        self.policies = FilePolicyStore(settings.policy_dir)
        for builtin in ("banking-default", "support-default", "legal-default"):
            if builtin not in self.policies.names():
                self.policies.save(builtin_policy(builtin))
        # Policy for playground queries (CSV datasets, dashboard and MCP); checked at start, not per request.
        self.playground_policy = settings.playground_policy
        self.policies.effective(self.playground_policy)
        self.playground = PlaygroundService(
            PlaygroundStore(settings.playground_db),
            lambda vault: Pipeline(self.policies.effective(self.playground_policy), detector=self.detector,
                                   classifier=self.classifier, vault=vault),
            self.playground_policy, traces=self.traces, audit=self.audit,
        )
        self.feedback = FeedbackStore(settings.feedback_db)
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    state = State(settings)
    mcp_holder: dict = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        from contextlib import AsyncExitStack

        # Load the NER model in the background so the first request does not wait several seconds.
        threading.Thread(target=lambda: state.detector.scan("Max Mustermann wohnt in Berlin."),
                         name="ner-warmup", daemon=True).start()
        async with AsyncExitStack() as stack:
            if "server" in mcp_holder:
                await stack.enter_async_context(mcp_holder["server"].session_manager.run())
            yield

    app = FastAPI(
        lifespan=lifespan,
        title="OpenAnonymizer API",
        version=anonymizer.__version__,
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
            raise HTTPException(status_code=403, detail="admin endpoints are disabled (no ANONYMIZER_ADMIN_KEYS)")
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
    # Playground CSV arrives as a JSON string: escaping (quotes, line breaks) can double its size.
    max_playground_body_bytes = 2 * PLAYGROUND_MAX_BYTES + 65_536

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
        path = request.url.path
        limit = (max_upload_body_bytes if path.startswith("/v1/documents/")
                 else max_playground_body_bytes if path == "/v1/playground/datasets" else max_body_bytes)
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

    @app.exception_handler(AccountError)
    async def account_error(_: Request, exc: AccountError) -> JSONResponse:
        status = 404 if "not found" in str(exc) else 400
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    # -- public ----------------------------------------------------------------
    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok"}

    ner_status: dict[str, str] = {}

    @app.get("/v1/info", tags=["system"])
    def info(_: User) -> dict:
        # Model availability does not change while the process runs: probe once, not on every call.
        if "de" not in ner_status:
            ner_status["de"] = "unavailable" if state.detector.scan("Herr Max Mustermann", "de").warnings else "available"
        return {
            "version": anonymizer.__version__,
            "ner": "disabled" if not settings.enable_ner else ner_status["de"],
            "vault": state.vault is not None,
            "admin_endpoints": admin_keys_exist(),
            "default_policy": settings.default_policy,
            "trace_content": settings.trace_content,
            "trace_retention_days": settings.trace_retention_days,
        }

    # -- core ------------------------------------------------------------------
    def usage(p: Principal) -> dict:
        """Who used the model and through which channel; stored on every trace."""
        return {"client": "dashboard" if p.kind == "session" else "api", "actor": p.label}

    def trace_scan(route: str, r, t0: float, p: Principal, **extra) -> None:
        state.traces.add(trace_from_scan(route, r, round((time.perf_counter() - t0) * 1000, 1), **usage(p), **extra),
                         p.org_id)

    @app.post("/v1/scan", response_model=ScanResponse, tags=["privacy"])
    def scan(req: TextRequest, p: User) -> ScanResponse:
        check_size(req.text)
        t0 = time.perf_counter()
        r = state.detector.scan(req.text, req.language)
        trace_scan("/v1/scan", r, t0, p)
        return ScanResponse(
            language=r.language, signals=r.signals, warnings=r.warnings,
            detections=[DetectionOut(**{**d.redacted(), "category": d.category.value, "signals": list(d.signals)})
                        for d in r.detections],
        )

    @app.post("/v1/classify", response_model=DocumentClassification, tags=["privacy"])
    def classify(req: ClassifyRequest, p: User) -> DocumentClassification:
        check_size(req.text)
        t0 = time.perf_counter()
        r = state.detector.scan(req.text, req.language)
        c = state.classifier.classify_text(req.text, r, corrections=req.corrections)
        trace_scan("/v1/classify", r, t0, p, risk=c.risk.value, needs_review=c.needs_review)
        return c

    @app.post("/v1/anonymize", response_model=AnonymizationResult, tags=["privacy"])
    def anonymize(req: AnonymizeRequest, p: User) -> AnonymizationResult:
        check_size(req.text)
        if req.namespace and state.vault is None:
            raise HTTPException(status_code=400, detail="namespace given but no vault configured (ANONYMIZER_VAULT_KEY)")
        t0 = time.perf_counter()
        r = state.detector.scan(req.text, req.language)
        cfg = AnonymizerConfig(methods=req.methods, include_role=req.include_role)
        result = OpenAnonymizer(cfg, vault=state.vault if req.namespace else None).anonymize(
            req.text, r, namespace=scoped(p, req.namespace))
        trace_scan("/v1/anonymize", r, t0, p, transformations=len(result.transformations))
        return result

    @app.post("/v1/protect", response_model=ProtectResponse, tags=["privacy"])
    def protect(req: ProtectRequest, p: User) -> ProtectResponse:
        """Full pipeline. ``text`` is only returned when the policy allows sending it to ``destination``."""
        check_size(req.text)
        if req.namespace and state.vault is None:
            raise HTTPException(status_code=400, detail="namespace given but no vault configured (ANONYMIZER_VAULT_KEY)")
        policy = state.policy_for(req.policy, req.policy_version, req.tenant, req.team)
        pipeline = Pipeline(policy, detector=state.detector, classifier=state.classifier,
                            vault=state.vault if req.namespace else None)
        t0 = time.perf_counter()
        result = pipeline.protect(req.text, req.destination, namespace=scoped(p, req.namespace),
                                  language=req.language, dry_run=req.dry_run)
        trace_id = None
        if not req.dry_run:
            trace = state.traces.add(trace_from_protect("/v1/protect", result, round((time.perf_counter() - t0) * 1000, 1),
                                                        original=req.text, **usage(p)), p.org_id)
            trace_id = trace.id
        text = None if req.dry_run else result.text
        return ProtectResponse(outcome=result.decision.outcome, allowed=result.allowed, text=text, trace_id=trace_id,
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
            raise HTTPException(status_code=400, detail="namespace given but no vault configured (ANONYMIZER_VAULT_KEY)")
        pipeline = Pipeline(state.policy_for(policy, None, None, None), detector=state.detector,
                            classifier=state.classifier, vault=state.vault if namespace else None)
        t0 = time.perf_counter()
        doc = protect_document(pipeline, data, file.filename, destination, scoped(p, namespace), language,
                               max_bytes=settings.max_upload_bytes)
        r = doc.result
        trace = trace_from_protect("/v1/documents/protect", r, round((time.perf_counter() - t0) * 1000, 1), **usage(p))
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

    # -- observability ---------------------------------------------------------
    @app.get("/v1/traces", response_model=list[Trace], tags=["observability"])
    def list_traces(p: User, limit: int = 50, outcome: str | None = None, route: str | None = None,
                    since: float | None = None, client: str | None = None) -> list[Trace]:
        return [_visible(t, p) for t in state.traces.list(limit, outcome, route, since, org_id=p.org_id, client=client)]

    @app.get("/v1/traces/{trace_id}", response_model=Trace, tags=["observability"])
    def get_trace(trace_id: str, p: User) -> Trace:
        trace = state.traces.get(trace_id, p.org_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return _visible(trace, p)

    def _visible(trace: Trace, p: Principal) -> Trace:
        """Content traces hold original values: admins only."""
        return trace if p.is_admin or not trace.content else trace.model_copy(update={"content": []})

    @app.get("/v1/metrics", tags=["observability"])
    def metrics(p: User, hours: int = 24) -> dict:
        return state.traces.metrics(max(1, min(hours, 24 * 90)), p.org_id)

    @app.post("/v1/restore", response_model=RestoreResult, tags=["privacy"])
    def restore_(req: RestoreRequest, p: AdminKey) -> RestoreResult:
        """Resolve placeholders with the vault. Admin API key only; recorded in the audit log
        (namespace and count, never values)."""
        check_size(req.text)
        if state.vault is None:
            raise HTTPException(status_code=400, detail="no vault configured (ANONYMIZER_VAULT_KEY)")
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

    @app.post("/v1/policies/dry-run", response_model=DryRunResult, tags=["policies"])
    def dry_run(req: DryRunRequest, _: User) -> DryRunResult:
        """Compare a candidate policy (not saved) with an active one on a sample text."""
        check_size(req.text)
        try:
            candidate = Policy.from_yaml(req.candidate_yaml)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=[
                {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()])
        active = state.policies.effective(req.against or settings.default_policy)
        return DryRunResult(**compare(active, candidate, req.text, req.language, req.destination)[0])

    def compare(active: Policy, candidate: Policy, text: str, language, destination: str) -> tuple[dict, dict[str, int]]:
        """Decision diff and protected preview of ``text`` under both policies, plus entity counts."""
        r = state.detector.scan(text, language)
        c = state.classifier.classify_text(text, r)
        live = PolicyEngine(active).evaluate(r.detections, c, destination)
        cand = PolicyEngine(candidate).evaluate(r.detections, c, destination, dry_run=True)

        def preview(policy: Policy) -> ProtectResult:
            # Throwaway vault: the sample shows real placeholders, the persistent vault stays untouched.
            return Pipeline(policy, detector=state.detector, classifier=state.classifier,
                            vault=InMemoryVault(VaultKey.generate())).protect_scan(text, r, destination, "dry-run")

        before, after = preview(active), preview(candidate)
        counts: dict[str, int] = defaultdict(int)
        for d in r.detections:
            counts[d.entity_type] += 1
        return {**diff_decisions(live, cand).model_dump(), "text_before": before.text, "text_after": after.text,
                "reasons_before": before.decision.reasons, "reasons_after": after.decision.reasons}, dict(counts)

    @app.post("/v1/policies/{name}/test", response_model=PolicyTestResult, tags=["policies"])
    def test_policy(name: str, req: PolicyTestRequest, _: User) -> PolicyTestResult:
        """Run a stored policy on a sample text, optionally with unsaved changes per entity type.
        Nothing is saved, traced or written to the vault; any API key may call it."""
        check_size(req.text)
        stored = state.policies.get(name)
        candidate = apply_changes(stored, req.changes, req.default_action) if req.changes or req.default_action else stored
        diff, counts = compare(state.policies.resolve(stored), state.policies.resolve(candidate),
                               req.text, req.language, req.destination)
        return PolicyTestResult(**diff, policy=stored.ref, entities=counts)

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

    @app.get("/v1/sources", tags=["system"])
    def sources(_: User) -> dict:
        """Which policy the playground (CSV) uses and whether MCP over HTTP is on."""
        return {"playground_policy": state.playground_policy, "mcp_http": settings.mcp_http}

    # -- playground ------------------------------------------------------------------------------
    # -- feedback (corrections from the Chat tab; raw text, admins read it) ------------------------
    @app.exception_handler(FeedbackError)
    async def feedback_error(_: Request, exc: FeedbackError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.post("/v1/feedback", status_code=201, tags=["feedback"])
    def create_feedback(req: FeedbackCreate, p: User) -> dict:
        """Mark what should have been detected (kind "missed", with a type) or was detected wrongly ("wrong").
        Stores the text: send test data only. Audited without the text."""
        check_size(req.text)
        row = state.feedback.add(p.org_id, req.text, [s.model_dump() for s in req.spans], p.label, req.policy,
                                 req.trace_id)
        state.audit.record(p.org_id, "create", "feedback", row["id"], p, after={
            "missed": sum(s["kind"] == "missed" for s in row["spans"]),
            "wrong": sum(s["kind"] == "wrong" for s in row["spans"]), "chars": len(req.text)})
        return {"id": row["id"], "spans": len(row["spans"])}

    @app.get("/v1/feedback", tags=["feedback"])
    def list_feedback(p: Admin, limit: int = 200) -> list[dict]:
        return state.feedback.list(p.org_id, limit)

    @app.get("/v1/feedback/export", tags=["feedback"])
    def export_feedback(p: Admin) -> Response:
        """All corrections as gold JSONL for training (ner_train.py --feedback). Audited."""
        body = state.feedback.export(p.org_id)
        state.audit.record(p.org_id, "export", "feedback", "all", p, after={"lines": body.count("\n")})
        return Response(body, media_type="application/x-ndjson",
                        headers={"Content-Disposition": 'attachment; filename="feedback.jsonl"'})

    @app.delete("/v1/feedback/{feedback_id}", status_code=204, tags=["feedback"])
    def delete_feedback(feedback_id: str, p: Admin) -> None:
        if not state.feedback.delete(p.org_id, feedback_id):
            raise HTTPException(status_code=404, detail="feedback not found")
        state.audit.record(p.org_id, "delete", "feedback", feedback_id, p)

    @app.exception_handler(PlaygroundError)
    async def playground_error(_: Request, exc: PlaygroundError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.get("/v1/playground/datasets", tags=["playground"])
    def list_datasets(p: User) -> list[dict]:
        return state.playground.list(p)

    @app.post("/v1/playground/datasets", status_code=201, tags=["playground"])
    def upload_dataset(req: PlaygroundUpload, p: SessionUser) -> dict:
        """Upload a CSV (text with header row). Dashboard sessions only; test data only."""
        return state.playground.upload(p, req.name, req.csv)

    @app.delete("/v1/playground/datasets/{dataset_id}", status_code=204, tags=["playground"])
    def delete_dataset(dataset_id: str, p: SessionUser) -> None:
        state.playground.delete(p, dataset_id)

    @app.put("/v1/playground/datasets/{dataset_id}/columns", tags=["playground"])
    def set_dataset_columns(dataset_id: str, req: PlaygroundColumns, p: SessionUser) -> dict:
        """Hide columns of an upload. Hidden columns stay stored but are never searched, shown or sent,
        neither in the dashboard nor over MCP. Dashboard sessions only."""
        return state.playground.set_hidden(p, dataset_id, req.hidden)

    @app.post("/v1/playground/datasets/{dataset_id}/query", tags=["playground"])
    def query_dataset(dataset_id: str, req: PlaygroundQuery, p: User) -> dict:
        """Protected rows as an AI client receives them. Dashboard sessions also get the originals for
        comparison; API keys never do."""
        return state.playground.query(p, dataset_id, req.query, req.columns, req.limit, req.offset,
                                      include_original=p.kind == "session", client="dashboard" if p.kind == "session" else "api")

    # -- MCP over HTTP -------------------------------------------------------------------------
    if settings.mcp_http:
        from starlette.routing import Route

        from anonymizer.mcp import AnonymizerTools, MCPConfig, http_server

        mcp_env = {k: v for k, v in settings.env.items() if k.startswith("ANONYMIZER_MCP_")}
        if settings.vault_key:
            mcp_env |= {"ANONYMIZER_VAULT_KEY": settings.vault_key, "ANONYMIZER_VAULT_PATH": str(settings.vault_path)}
        tools = AnonymizerTools(MCPConfig.from_env(mcp_env), detector=state.detector,
                          playground=state.playground,
                          traces=state.traces, policy_provider=lambda: state.policies.effective(settings.default_policy))
        hosts = [h.strip() for h in settings.env.get("ANONYMIZER_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
        server, endpoint = http_server(tools, lambda token: resolve_token(token), hosts)
        mcp_holder["server"] = server
        app.router.routes.append(Route("/mcp", endpoint=endpoint))

    return app


def run() -> None:  # pragma: no cover
    import os

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host=os.environ.get("ANONYMIZER_HOST", "127.0.0.1"),
                port=int(os.environ.get("ANONYMIZER_PORT", "8080")), access_log=False)
