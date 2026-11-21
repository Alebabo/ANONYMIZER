"""Request/response schemas. Responses never contain raw detected values;
clients already hold the text and can use the offsets."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from anonymizer.anonymize import Method
from anonymizer.classify import DocumentClassification, RiskLevel
from anonymizer.models import Signal
from anonymizer.policy import Action, DecisionDiff, Outcome, PolicyDecision

Language = Literal["de", "en"]
Destination = Literal["external", "local"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextRequest(_Strict):
    text: str = Field(min_length=1)
    language: Language | None = None


class DetectionOut(BaseModel):
    id: str
    entity_type: str
    category: str
    start: int
    end: int
    confidence: float
    recognizer: str
    validated: bool | None
    signals: list[str]
    attributes: dict[str, str]


class ScanResponse(BaseModel):
    language: str
    detections: list[DetectionOut]
    signals: list[Signal]
    warnings: list[str]


class ClassifyRequest(TextRequest):
    corrections: dict[str, RiskLevel] = Field(default_factory=dict, description="detection id -> risk")


class AnonymizeRequest(TextRequest):
    methods: dict[str, Method] = Field(default_factory=dict, description="entity type -> method")
    namespace: str | None = Field(None, max_length=128,
                                  description="Vault namespace (e.g. matter id); enables reversible pseudonyms")
    include_role: bool = False


class ProtectRequest(TextRequest):
    destination: Destination = "external"
    namespace: str | None = Field(None, max_length=128)
    policy: str | None = Field(None, description="policy name; default: scope resolution / default policy")
    policy_version: int | None = None
    tenant: str | None = None
    team: str | None = None
    dry_run: bool = False


class ProtectResponse(BaseModel):
    outcome: Outcome
    allowed: bool
    text: str | None
    risk: RiskLevel
    decision: PolicyDecision
    classification: DocumentClassification
    trace_id: str | None = None


class RestoreRequest(_Strict):
    text: str = Field(min_length=1)
    namespace: str = Field(min_length=1, max_length=128)


class PolicyCreate(_Strict):
    yaml: str = Field(min_length=1, max_length=100_000, description="Policy in YAML; version must be latest + 1")


class PolicySummary(BaseModel):
    name: str
    version: int
    hash: str
    scope: dict[str, Any]


class DryRunRequest(TextRequest):
    candidate_yaml: str = Field(min_length=1, max_length=100_000)
    destination: Destination = "external"
    against: str | None = Field(None, description="active policy name to compare with (default: default policy)")


class DryRunResult(DecisionDiff):
    """Decision diff plus the protected sample text under both policies (None: not sent)."""
    text_before: str | None = None
    text_after: str | None = None
    reasons_before: list[str] = []
    reasons_after: list[str] = []


class PolicyTestRequest(TextRequest):
    changes: dict[str, Action | None] = Field(
        default_factory=dict, max_length=200,
        description="unsaved change per entity type, e.g. {\"email\": \"allow\"}; null = follow default_action")
    default_action: Action | None = Field(None, description="unsaved default for types without their own action")
    destination: Destination = "external"


class PolicyTestResult(DryRunResult):
    """Test of a stored policy on a sample text. Without changes, before and after are the same."""
    policy: str
    entities: dict[str, int] = {}


# -- accounts ----------------------------------------------------------------------

class LoginRequest(_Strict):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(_Strict):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class ProxyUpstreamToggle(_Strict):
    enabled: bool


class ApiKeyCreate(_Strict):
    name: str = Field(min_length=1, max_length=100)
    role: Literal["user", "admin"] = "user"


class MemberCreate(_Strict):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024, description="initial password, min. 12 characters")
    role: Literal["admin", "member"] = "member"


class MemberUpdate(_Strict):
    name: str | None = Field(None, min_length=1, max_length=100)
    role: Literal["admin", "member"] | None = None
    disabled: bool | None = None


class OrganizationUpdate(_Strict):
    name: str | None = Field(None, min_length=1, max_length=100)
    trace_retention_days: int | None = Field(None, ge=1, le=3650)


class PromptMessageIn(_Strict):
    role: str = Field(min_length=1, max_length=32)
    content: str


class PromptCreate(_Strict):
    name: str = Field(min_length=1, max_length=128)
    prompt: str | list[PromptMessageIn]
    config: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(None, max_length=500)


class PromptLabelSet(_Strict):
    version: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=32)


class PlaygroundUpload(_Strict):
    name: str = Field(min_length=1, max_length=120)
    csv: str = Field(min_length=1, max_length=100 * 1024 * 1024)  # playground.MAX_BYTES


class FeedbackSpan(_Strict):
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    kind: Literal["missed", "wrong"]
    label: str = Field("", max_length=40, description="type for 'missed' (person, case_number, …); detected type for 'wrong'")


class FeedbackCreate(_Strict):
    text: str = Field(min_length=1, max_length=20_000)
    spans: list[FeedbackSpan] = Field(min_length=1, max_length=200)
    policy: str | None = Field(None, max_length=64)
    trace_id: str | None = Field(None, max_length=40)


class PlaygroundColumns(_Strict):
    hidden: list[str] = Field(default_factory=list, max_length=200)


class PlaygroundQuery(_Strict):
    query: str | None = Field(default=None, max_length=200)
    columns: list[str] | None = Field(default=None, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
