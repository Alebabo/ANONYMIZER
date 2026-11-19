"""Value transformations that need no state: masking and generalization."""

from __future__ import annotations

import re

from anonymizer.models import EntityType as E

# --------------------------------------------------------------------------
# Masking: format-preserving, keeps a configurable prefix/suffix of the
# alphanumeric characters.
# --------------------------------------------------------------------------

DEFAULT_MASK_KEEP: dict[str, tuple[int, int]] = {
    E.IBAN: (4, 4),
    E.CREDIT_CARD: (0, 4),
    E.PHONE: (0, 2),
    E.TAX_ID: (0, 2),
    E.SOCIAL_SECURITY_NUMBER: (0, 2),
    E.BIC: (4, 0),
}


def mask(value: str, entity_type: str, keep: dict[str, tuple[int, int]] | None = None, char: str = "*") -> str:
    if entity_type == E.EMAIL and "@" in value:
        local, domain = value.split("@", 1)
        return f"{local[:1]}{char * 3}@{domain}"
    start, end = (keep or DEFAULT_MASK_KEEP).get(entity_type, (1, 0))
    alnum_positions = [i for i, ch in enumerate(value) if ch.isalnum()]
    total = len(alnum_positions)
    if total <= start + end:  # too short to reveal anything safely
        start, end = 0, 0
    hidden = set(alnum_positions[start:total - end])
    return "".join(char if i in hidden else ch for i, ch in enumerate(value))


# --------------------------------------------------------------------------
# Generalization: replace a value by a coarser one.
# --------------------------------------------------------------------------

_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_DE_CITY = re.compile(r"\b\d{5}\s+(?P<city>[A-ZÄÖÜ][\wäöüß\- ]+)$")
_US_CITY = re.compile(r",\s(?P<city>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?(?:,\s[A-Z]{2})?)(?:\s\d{5})?$")
_CURRENCY = re.compile(r"€|EUR|Euro|USD|US-Dollar|Dollar|\$|CHF|GBP|£")


def _parse_amount(value: str) -> float | None:
    digits = re.sub(r"[^\d.,]", "", value)
    if not digits:
        return None
    # Decimal separator = last separator followed by exactly 1-2 digits.
    m = re.search(r"[.,](\d{1,2})$", digits)
    if m:
        integer, decimals = digits[: m.start()], m.group(1)
    else:
        integer, decimals = digits, "0"
    integer = re.sub(r"[.,]", "", integer) or "0"
    try:
        return float(f"{integer}.{decimals}")
    except ValueError:
        return None


def _amount_bucket(amount: float) -> str:
    bounds = [100, 1_000, 10_000, 100_000, 1_000_000]
    lower = 0
    for b in bounds:
        if amount < b:
            return f"{lower:,}–{b:,}".replace(",", ".") if lower else f"< {b:,}".replace(",", ".")
        lower = b
    return f"> {bounds[-1]:,}".replace(",", ".")


def generalize(value: str, entity_type: str) -> str | None:
    """Coarser representation, or None if no sensible generalization exists."""
    if entity_type in (E.DATE, E.DATE_OF_BIRTH):
        m = _YEAR.search(value)
        return m.group(1) if m else None
    if entity_type == E.ADDRESS:
        for regex in (_DE_CITY, _US_CITY):
            m = regex.search(value.strip())
            if m:
                return m.group("city").strip()
        return None
    if entity_type == E.MONEY:
        amount = _parse_amount(value)
        if amount is None:
            return None
        currency = _CURRENCY.search(value)
        unit = currency.group(0) if currency else ""
        unit = {"€": "EUR", "$": "USD", "£": "GBP", "Euro": "EUR"}.get(unit, unit)
        return f"{_amount_bucket(amount)} {unit}".strip()
    return None
