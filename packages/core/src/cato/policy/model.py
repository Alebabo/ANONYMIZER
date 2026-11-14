"""Policy model (YAML).

Example::

    name: legal-default
    version: 1
    rules:
      - entity: person
        action: pseudonymize
      - entity: health_data
        action: block
      - category: special_category
        destinations: [external]
        action: local_only
        priority: 10
    document_rules:
      - min_risk: critical
        signals: [criminal_proceeding]
        destinations: [external]
        action: review
    default_action: allow
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cato.anonymize import Method
from cato.classify import RiskLevel


class Action(str, Enum):
    ALLOW = "allow"
    REPLACE = "replace"
    GENERALIZE = "generalize"
    MASK = "mask"
    PSEUDONYMIZE = "pseudonymize"
    TOKENIZE = "tokenize"
    REDACT = "redact"
    REVIEW = "review"          # needs human approval before leaving
    LOCAL_ONLY = "local_only"  # may only be processed by a local model
    BLOCK = "block"            # must never leave

    @property
    def severity(self) -> int:
        return _SEVERITY[self]


# Conflict tie-breaker: the more restrictive action wins.
_SEVERITY = {a: i for i, a in enumerate(Action)}

ACTION_TO_METHOD: dict[Action, Method] = {
    Action.ALLOW: Method.KEEP,
    Action.REPLACE: Method.REPLACE,
    Action.GENERALIZE: Method.GENERALIZE,
    Action.MASK: Method.MASK,
    Action.PSEUDONYMIZE: Method.PSEUDONYMIZE,
    Action.TOKENIZE: Method.TOKENIZE,
    Action.REDACT: Method.REDACT,
    # Gate actions: if text is produced anyway (e.g. preview), fail closed.
    Action.REVIEW: Method.REDACT,
    Action.LOCAL_ONLY: Method.REDACT,
    Action.BLOCK: Method.REDACT,
}

GATE_ACTIONS = {Action.REVIEW, Action.LOCAL_ONLY, Action.BLOCK}
DESTINATIONS = {"external", "local"}


def _as_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    return [value] if isinstance(value, str) else list(value)


class Rule(BaseModel):
    """Entity rule. All given conditions must hold (AND); list values are OR."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    description: str | None = None
    entity: list[str] | None = None
    category: list[str] | None = None
    risk: list[RiskLevel] | None = None
    min_risk: RiskLevel | None = None
    role: list[str] | None = None
    signals: list[str] | None = None          # any of these near the entity
    document_signals: list[str] | None = None  # any of these anywhere in the document
    max_confidence: float | None = Field(None, ge=0, le=1)
    destinations: list[str] | None = None
    action: Action
    priority: int = 0
    allow_critical: bool = False  # explicit opt-out of the critical floor

    @field_validator("entity", "category", "role", "signals", "document_signals", "destinations", "risk",
                     mode="before")
    @classmethod
    def _listify(cls, v: Any) -> list[str] | None:
        return _as_list(v)

    @field_validator("destinations")
    @classmethod
    def _known_destinations(cls, v: list[str] | None) -> list[str] | None:
        if v and (unknown := set(v) - DESTINATIONS):
            raise ValueError(f"unknown destinations {sorted(unknown)}; use {sorted(DESTINATIONS)}")
        return v


class DocumentRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    description: str | None = None
    risk: list[RiskLevel] | None = None
    min_risk: RiskLevel | None = None
    signals: list[str] | None = None
    entity_present: list[str] | None = None
    destinations: list[str] | None = None
    action: Action
    priority: int = 0

    @field_validator("risk", "signals", "entity_present", "destinations", mode="before")
    @classmethod
    def _listify(cls, v: Any) -> list[str] | None:
        return _as_list(v)

    @field_validator("destinations")
    @classmethod
    def _known_destinations(cls, v: list[str] | None) -> list[str] | None:
        return Rule._known_destinations(v)

    @field_validator("action")
    @classmethod
    def _gate_only(cls, v: Action) -> Action:
        if v not in GATE_ACTIONS | {Action.ALLOW}:
            raise ValueError("document rules support allow, review, local_only and block")
        return v


class Scope(BaseModel):
    tenant: str | None = None
    team: str | None = None


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")
    version: int = Field(1, ge=1)
    description: str | None = None
    extends: str | None = None
    scope: Scope = Field(default_factory=Scope)
    rules: list[Rule] = Field(default_factory=list)
    document_rules: list[DocumentRule] = Field(default_factory=list)
    default_action: Action = Action.REDACT
    # Entities classified critical never pass unchanged to external
    # destinations unless a rule sets allow_critical.
    critical_floor: bool = True
    critical_floor_action: Action = Action.PSEUDONYMIZE
    # Entities flagged needs_review by classification put the document into review.
    review_uncertain: bool = False

    @model_validator(mode="after")
    def _ids(self) -> "Policy":
        for prefix, items in (("rule", self.rules), ("doc_rule", self.document_rules)):
            for i, r in enumerate(items, 1):
                if r.id is None:
                    r.id = f"{prefix}_{i}"
            ids = [r.id for r in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {prefix} ids")
        if self.critical_floor_action in (Action.ALLOW,):
            raise ValueError("critical_floor_action must not be allow")
        return self

    # -- serialization ---------------------------------------------------------
    @classmethod
    def from_yaml(cls, text: str) -> "Policy":
        return cls.model_validate(yaml.safe_load(text))

    @classmethod
    def from_file(cls, path: str | Path) -> "Policy":
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True)

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    @property
    def ref(self) -> str:
        return f"{self.name}@v{self.version}"
