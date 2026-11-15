"""Request/response schemas. Responses never contain raw detected values;
clients already hold the text and can use the offsets."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cato.anonymize import Method
from cato.classify import DocumentClassification, RiskLevel
from cato.models import Signal
from cato.policy import Outcome, PolicyDecision

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
