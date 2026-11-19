"""Checksum validators. Deterministic, no external dependencies."""

from __future__ import annotations

import re
from collections import Counter

# Official IBAN lengths for frequently seen countries (ISO 13616 registry).
IBAN_LENGTHS: dict[str, int] = {
    "AD": 24, "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24,
    "DE": 22, "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22,
    "GR": 27, "HR": 21, "HU": 28, "IE": 22, "IS": 26, "IT": 27, "LI": 21,
    "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MT": 31, "NL": 18, "NO": 15,
    "PL": 28, "PT": 25, "RO": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27,
    "TR": 26,
}


def compact(value: str) -> str:
    return re.sub(r"[\s-]", "", value).upper()


def iban_is_valid(value: str) -> bool:
    iban = compact(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    expected = IBAN_LENGTHS.get(iban[:2])
    if expected is not None and len(iban) != expected:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


def luhn_is_valid(value: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", value)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def german_tax_id_check_digit(first_ten: str) -> int:
    """ISO 7064 MOD 11,10 as used by the German Steuer-Identifikationsnummer."""
    product = 10
    for ch in first_ten:
        s = (int(ch) + product) % 10
        if s == 0:
            s = 10
        product = (s * 2) % 11
    check = 11 - product
    return 0 if check == 10 else check


def german_tax_id_is_valid(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11 or digits[0] == "0":
        return False
    counts = Counter(digits[:10])
    repeated = [d for d, c in counts.items() if c > 1]
    # Exactly one digit occurs two or three times, no digit more often.
    if len(repeated) != 1 or counts[repeated[0]] > 3:
        return False
    return german_tax_id_check_digit(digits[:10]) == int(digits[10])


def phone_digit_count_ok(value: str) -> bool:
    return 7 <= len(re.sub(r"\D", "", value)) <= 15


def us_ssn_is_plausible(value: str) -> bool:
    m = re.fullmatch(r"(\d{3})-(\d{2})-(\d{4})", value)
    if not m:
        return False
    area, group, serial = m.groups()
    return area not in {"000", "666"} and not area.startswith("9") and group != "00" and serial != "0000"


def contains_digit(value: str) -> bool:
    return any(ch.isdigit() for ch in value)
