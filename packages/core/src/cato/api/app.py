"""Cato REST API.

Security properties:
* Every /v1 endpoint requires an API key (``Authorization: Bearer <key>`` or
  ``X-API-Key``). Restore and policy writes require an admin key.
* Request bodies are never logged. The access log contains method, path,
  status, latency and a request id only.
* Validation errors never echo the submitted input (FastAPI's default 422
  response would).
* Text size is capped (``CATO_MAX_CHARS``).

Note: no ``from __future__ import annotations`` here. FastAPI must resolve
the locally defined ``User``/``Admin`` dependency types at definition time;
with string annotations they silently turn into body parameters and auth
breaks (covered by tests/test_api.py::test_endpoints_require_key).
"""


import logging
import time
import uuid
from typing import Annotated

import base64

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

import cato
from cato.anonymize import Anonymizer, AnonymizerConfig, LeakError, restore
from cato.api.schemas import (
    AnonymizeRequest, ClassifyRequest, DetectionOut, DryRunRequest, PolicyCreate, PolicySummary, ProtectRequest,
    ProtectResponse, RestoreRequest, ScanResponse, TextRequest,
)
from cato.api.settings import Settings
from cato.anonymize.engine import AnonymizationResult, RestoreResult
from cato.classify import Classifier, DocumentClassification
from cato.detect import Detector, DetectorConfig
from cato.pipeline import Pipeline
from cato.policy import (
    DecisionDiff, FilePolicyStore, Policy, PolicyEngine, PolicyError, builtin_policy, diff_decisions,
)
from cato.documents import DocumentError, protect_document
from cato.vault import FileVault, VaultError, VaultKey

log = logging.getLogger("cato.api")


class State:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.detector = Detector(DetectorConfig(enable_ner=settings.enable_ner))
        self.classifier = Classifier()
        self.vault = (FileVault(settings.vault_path, VaultKey.from_b64(settings.vault_key))
                      if settings.vault_key else None)
        self.policies = FilePolicyStore(settings.policy_dir)
        if "legal-default" not in self.policies.names():
            self.policies.save(builtin_policy())

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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    state = State(settings)
    app = FastAPI(
        title="Cato API",
        version=cato.__version__,
        description="Privacy infrastructure for legal AI: detect, classify, anonymize and control sensitive "
                    "information before AI models process it. Responses contain offsets, never raw values.",
    )

    # -- auth -----------------------------------------------------------------
    def require_key(request: Request) -> None:
        key = _key_from(request)
        if not key or not settings.is_api_key(key):
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    def require_admin(request: Request) -> None:
        key = _key_from(request)
        if not settings.admin_key_hashes:
            raise HTTPException(status_code=403, detail="admin endpoints are disabled (no CATO_ADMIN_KEYS)")
        if not key or not settings.is_admin_key(key):
            raise HTTPException(status_code=403, detail="admin key required")

    User = Annotated[None, Depends(require_key)]
    Admin = Annotated[None, Depends(require_admin)]

    def check_size(text: str) -> None:
        if len(text) > settings.max_chars:
            raise HTTPException(status_code=413, detail=f"text exceeds {settings.max_chars} characters")

    # -- middleware & error handling ------------------------------------------
    @app.middleware("http")
    async def access_log(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
        start = time.perf_counter()
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
            "admin_endpoints": bool(settings.admin_key_hashes),
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
    def anonymize(req: AnonymizeRequest, _: User) -> AnonymizationResult:
        check_size(req.text)
        if req.namespace and state.vault is None:
            raise HTTPException(status_code=400, detail="namespace given but no vault configured (CATO_VAULT_KEY)")
        r = state.detector.scan(req.text, req.language)
        cfg = AnonymizerConfig(methods=req.methods, include_role=req.include_role)
        return Anonymizer(cfg, vault=state.vault if req.namespace else None).anonymize(
            req.text, r, namespace=req.namespace)

    @app.post("/v1/protect", response_model=ProtectResponse, tags=["privacy"])
    def protect(req: ProtectRequest, _: User) -> ProtectResponse:
        """Full pipeline. ``text`` is only returned when the policy allows sending it to ``destination``."""
        check_size(req.text)
        if req.namespace and state.vault is None:
            raise HTTPException(status_code=400, detail="namespace given but no vault configured (CATO_VAULT_KEY)")
        policy = state.policy_for(req.policy, req.policy_version, req.tenant, req.team)
        pipeline = Pipeline(policy, detector=state.detector, classifier=state.classifier,
                            vault=state.vault if req.namespace else None)
        result = pipeline.protect(req.text, req.destination, namespace=req.namespace, language=req.language,
                                  dry_run=req.dry_run)
        text = None if req.dry_run else result.text
        return ProtectResponse(outcome=result.decision.outcome, allowed=result.allowed, text=text,
                               risk=result.classification.risk, decision=result.decision,
                               classification=result.classification)

    @app.post("/v1/documents/protect", tags=["documents"])
    async def protect_document_(
        _: User,
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
        doc = protect_document(pipeline, data, file.filename, destination, namespace, language,
                               max_bytes=settings.max_upload_bytes)
        r = doc.result
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

    @app.post("/v1/restore", response_model=RestoreResult, tags=["privacy"])
    def restore_(req: RestoreRequest, _: Admin) -> RestoreResult:
        """Resolve placeholders with the vault. Admin key only; the call is logged without content."""
        check_size(req.text)
        if state.vault is None:
            raise HTTPException(status_code=400, detail="no vault configured (CATO_VAULT_KEY)")
        result = restore(req.text, state.vault, req.namespace)
        log.warning("restore performed: %d placeholder(s) resolved", result.restored)
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
    def create_policy(req: PolicyCreate, _: Admin) -> PolicySummary:
        try:
            policy = Policy.from_yaml(req.yaml)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=[
                {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()])
        saved = state.policies.save(policy)
        log.warning("policy saved: %s %s", saved.ref, saved.content_hash)
        return PolicySummary(name=saved.name, version=saved.version, hash=saved.content_hash,
                             scope=saved.scope.model_dump())

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

    return app


def run() -> None:  # pragma: no cover
    import os

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host=os.environ.get("CATO_HOST", "127.0.0.1"),
                port=int(os.environ.get("CATO_PORT", "8080")), access_log=False)
