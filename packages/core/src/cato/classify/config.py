"""Classification configuration. All rules are data, evaluated deterministically."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from cato.models import EntityType as E


class RiskLevel(str, Enum):
    LOW = "low"              # Level 1 – uncritical
    SENSITIVE = "sensitive"  # Level 2 – grey, needs policy check
    CRITICAL = "critical"    # Level 3 – must not leave without strong protection

    @property
    def level(self) -> int:
        return _ORDER[self]

    def __lt__(self, other: "RiskLevel") -> bool:  # type: ignore[override]
        return self.level < other.level

    def __le__(self, other: "RiskLevel") -> bool:  # type: ignore[override]
        return self.level <= other.level

    def __gt__(self, other: "RiskLevel") -> bool:  # type: ignore[override]
        return self.level > other.level

    def __ge__(self, other: "RiskLevel") -> bool:  # type: ignore[override]
        return self.level >= other.level

    def lower(self) -> "RiskLevel":
        return _BY_LEVEL[max(1, self.level - 1)]


_ORDER = {RiskLevel.LOW: 1, RiskLevel.SENSITIVE: 2, RiskLevel.CRITICAL: 3}
_BY_LEVEL = {v: k for k, v in _ORDER.items()}

L, S, C = RiskLevel.LOW, RiskLevel.SENSITIVE, RiskLevel.CRITICAL

DEFAULT_BASE_RISK: dict[str, RiskLevel] = {
    # Critical by nature
    E.IBAN: C, E.CREDIT_CARD: C, E.TAX_ID: C, E.SOCIAL_SECURITY_NUMBER: C, E.DATE_OF_BIRTH: C,
    E.HEALTH_DATA: C, E.BIOMETRIC_DATA: C, E.SPECIAL_CATEGORY: C, E.CRIMINAL_RECORD: C,
    E.PRIVILEGE_MARKER: C,
    # Personal or confidential, policy decides
    E.PERSON: S, E.ADDRESS: S, E.EMAIL: S, E.PHONE: S, E.CASE_NUMBER: S, E.BIC: S, E.TAX_NUMBER: S,
    E.BUSINESS_SECRET_MARKER: S,
    # Public or low value on their own
    E.ORGANIZATION: L, E.LOCATION: L, E.DATE: L, E.MONEY: L, E.VAT_ID: L, E.COURT: L, E.LEGAL_CITATION: L,
}

# Procedural roles that make a person critical regardless of other context.
DEFAULT_ROLE_RISK: dict[str, RiskLevel] = {
    "client": C, "accused": C, "injured_party": C, "decedent": S,
    "plaintiff": S, "defendant": S, "witness": S, "applicant": S, "respondent": S,
    "employee": S, "employer": S,
}


class SignalRule(BaseModel):
    """Raise entities of ``entity_types`` to at least ``min_risk`` when one of
    ``signals`` occurs near them (or anywhere in the document if ``scope``
    is ``document``)."""

    name: str
    signals: list[str]
    entity_types: list[str]
    min_risk: RiskLevel
    scope: str = Field("entity", pattern="^(entity|document)$")


DEFAULT_SIGNAL_RULES: list[SignalRule] = [
    SignalRule(name="client_context", signals=["client_relationship"],
               entity_types=[E.PERSON, E.ADDRESS, E.EMAIL, E.PHONE, E.CASE_NUMBER, E.DATE], min_risk=C),
    SignalRule(name="criminal_context", signals=["criminal_proceeding"],
               entity_types=[E.PERSON, E.ADDRESS, E.EMAIL, E.PHONE, E.CASE_NUMBER, E.DATE], min_risk=C),
    SignalRule(name="litigation_context", signals=["litigation"],
               entity_types=[E.PERSON, E.CASE_NUMBER, E.ORGANIZATION], min_risk=S),
    SignalRule(name="financial_context", signals=["employment", "financial_distress"],
               entity_types=[E.MONEY], min_risk=S),
    SignalRule(name="distress_context", signals=["financial_distress"],
               entity_types=[E.PERSON, E.MONEY], min_risk=C),
    SignalRule(name="confidential_document", signals=["confidential"], scope="document",
               entity_types=[E.ORGANIZATION, E.MONEY, E.DATE], min_risk=S),
]

# Entity types that the example context may lower by one level. Validated
# identifiers and special categories are never lowered.
DEFAULT_EXAMPLE_LOWERABLE = [E.PERSON, E.ADDRESS, E.EMAIL, E.PHONE, E.ORGANIZATION, E.DATE, E.MONEY, E.LOCATION]

# Signals that contradict "this is just an example". If present, no lowering.
DEFAULT_EXAMPLE_BLOCKERS = ["client_relationship", "criminal_proceeding", "confidential"]


class Override(BaseModel):
    """Fixed risk for matching detections, e.g. from an organisation policy."""

    risk: RiskLevel
    entity_type: str | None = None
    category: str | None = None
    recognizer: str | None = None
    reason: str = "configured override"


class LinkRule(BaseModel):
    """Raise ``entity_types`` to ``min_risk`` when an entity of one of
    ``linked_categories`` occurs within ``window`` characters in the same
    paragraph (e.g. a person next to health data is the data subject)."""

    name: str
    entity_types: list[str]
    linked_categories: list[str]
    min_risk: RiskLevel
    window: int = 200


DEFAULT_LINK_RULES: list[LinkRule] = [
    LinkRule(name="data_subject_of_special_category", entity_types=[E.PERSON],
             linked_categories=["special_category"], min_risk=C),
]


class ClassifierConfig(BaseModel):
    base_risk: dict[str, RiskLevel] = Field(default_factory=lambda: dict(DEFAULT_BASE_RISK))
    unknown_type_risk: RiskLevel = RiskLevel.SENSITIVE
    role_risk: dict[str, RiskLevel] = Field(default_factory=lambda: dict(DEFAULT_ROLE_RISK))
    signal_rules: list[SignalRule] = Field(default_factory=lambda: list(DEFAULT_SIGNAL_RULES))
    example_lowering: bool = True
    example_lowerable: list[str] = Field(default_factory=lambda: list(DEFAULT_EXAMPLE_LOWERABLE))
    example_blockers: list[str] = Field(default_factory=lambda: list(DEFAULT_EXAMPLE_BLOCKERS))
    link_rules: list[LinkRule] = Field(default_factory=lambda: list(DEFAULT_LINK_RULES))
    overrides: list[Override] = Field(default_factory=list)
    # Detections below this confidence are flagged for manual review if their
    # risk is at least SENSITIVE (uncertain low-risk hits do not block).
    review_threshold: float = Field(0.6, ge=0.0, le=1.0)
    # Document is at least SENSITIVE once this many sensitive entities occur.
    document_sensitive_count: int = Field(1, ge=1)

    @field_validator("base_risk", "role_risk", mode="before")
    @classmethod
    def _merge_defaults(cls, value, info):
        defaults = DEFAULT_BASE_RISK if info.field_name == "base_risk" else DEFAULT_ROLE_RISK
        return {**{str(getattr(k, "value", k)): v for k, v in defaults.items()}, **(value or {})}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ClassifierConfig":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
