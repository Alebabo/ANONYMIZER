"""Core data model shared by all OpenAnonymizer engines."""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Category(str, Enum):
    PERSONAL_DATA = "personal_data"
    FINANCIAL_DATA = "financial_data"
    LEGAL_DATA = "legal_data"
    PROFESSIONAL_SECRET = "professional_secret"
    BUSINESS_SECRET = "business_secret"
    SPECIAL_CATEGORY = "special_category"
    PUBLIC_REFERENCE = "public_reference"


class EntityType(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    ADDRESS = "address"
    EMAIL = "email"
    PHONE = "phone"
    DATE = "date"
    DATE_OF_BIRTH = "date_of_birth"
    IBAN = "iban"
    BIC = "bic"
    CREDIT_CARD = "credit_card"
    MONEY = "money"
    TAX_ID = "tax_id"
    TAX_NUMBER = "tax_number"
    VAT_ID = "vat_id"
    SOCIAL_SECURITY_NUMBER = "social_security_number"
    CASE_NUMBER = "case_number"
    COURT = "court"
    LEGAL_CITATION = "legal_citation"
    HEALTH_DATA = "health_data"
    BIOMETRIC_DATA = "biometric_data"
    SPECIAL_CATEGORY = "special_category"
    CRIMINAL_RECORD = "criminal_record"
    PRIVILEGE_MARKER = "privilege_marker"
    BUSINESS_SECRET_MARKER = "business_secret_marker"


DEFAULT_CATEGORIES: dict[str, Category] = {
    EntityType.PERSON: Category.PERSONAL_DATA,
    EntityType.ORGANIZATION: Category.PERSONAL_DATA,
    EntityType.LOCATION: Category.PERSONAL_DATA,
    EntityType.ADDRESS: Category.PERSONAL_DATA,
    EntityType.EMAIL: Category.PERSONAL_DATA,
    EntityType.PHONE: Category.PERSONAL_DATA,
    EntityType.DATE: Category.PERSONAL_DATA,
    EntityType.DATE_OF_BIRTH: Category.PERSONAL_DATA,
    EntityType.IBAN: Category.FINANCIAL_DATA,
    EntityType.BIC: Category.FINANCIAL_DATA,
    EntityType.CREDIT_CARD: Category.FINANCIAL_DATA,
    EntityType.MONEY: Category.FINANCIAL_DATA,
    EntityType.TAX_ID: Category.PERSONAL_DATA,
    EntityType.TAX_NUMBER: Category.FINANCIAL_DATA,
    EntityType.VAT_ID: Category.FINANCIAL_DATA,
    EntityType.SOCIAL_SECURITY_NUMBER: Category.PERSONAL_DATA,
    EntityType.CASE_NUMBER: Category.LEGAL_DATA,
    EntityType.COURT: Category.PUBLIC_REFERENCE,
    EntityType.LEGAL_CITATION: Category.PUBLIC_REFERENCE,
    EntityType.HEALTH_DATA: Category.SPECIAL_CATEGORY,
    EntityType.BIOMETRIC_DATA: Category.SPECIAL_CATEGORY,
    EntityType.SPECIAL_CATEGORY: Category.SPECIAL_CATEGORY,
    EntityType.CRIMINAL_RECORD: Category.SPECIAL_CATEGORY,
    EntityType.PRIVILEGE_MARKER: Category.PROFESSIONAL_SECRET,
    EntityType.BUSINESS_SECRET_MARKER: Category.BUSINESS_SECRET,
}


# Whitespace inside a multi-word value: spaces/tabs with at most one line
# break, so "Max\nMustermann" (wrapped line) still counts as one mention.
INNER_WS = r"(?:[^\S\n]+|[^\S\n]*\n[^\S\n]*)"


def detection_id(entity_type: str, start: int, end: int) -> str:
    """Stable id derived from type and offsets only (never from the raw value)."""
    digest = hashlib.sha1(f"{entity_type}:{start}:{end}".encode()).hexdigest()
    return f"det_{digest[:12]}"


class Detection(BaseModel):
    """A single sensitive span found in the input text.

    ``text`` holds the raw value. Callers that persist or log detections must
    drop it (see ``Detection.redacted()``).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    entity_type: str
    category: Category
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    recognizer: str
    validated: bool | None = None
    signals: tuple[str, ...] = ()
    attributes: dict[str, str] = Field(default_factory=dict)

    def redacted(self) -> dict[str, Any]:
        """Metadata view without the raw value, safe for logs and traces."""
        return self.model_dump(exclude={"text"})


class Suppressed(BaseModel):
    """A candidate that lost overlap resolution. Kept for auditability."""

    detection: Detection
    overlapped_by: str
    reason: str


class Signal(BaseModel):
    """A context cue found in the document (e.g. 'criminal_proceeding')."""

    name: str
    start: int
    end: int


class ScanResult(BaseModel):
    language: str
    detections: list[Detection]
    suppressed: list[Suppressed] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def document_signals(self) -> set[str]:
        return {s.name for s in self.signals}


def make_detection(
    entity_type: str,
    category: Category,
    start: int,
    end: int,
    text: str,
    confidence: float,
    recognizer: str,
    validated: bool | None = None,
    attributes: dict[str, str] | None = None,
) -> Detection:
    # Normalise first: an f-string renders a (str, Enum) member as
    # "EntityType.PERSON", which would give the same span two different ids.
    entity_type = str(entity_type.value if isinstance(entity_type, Enum) else entity_type)
    return Detection(
        id=detection_id(entity_type, start, end),
        entity_type=entity_type,
        category=category,
        start=start,
        end=end,
        text=text,
        confidence=round(min(max(confidence, 0.0), 1.0), 4),
        recognizer=recognizer,
        validated=validated,
        attributes=attributes or {},
    )
