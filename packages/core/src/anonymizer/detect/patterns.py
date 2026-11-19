"""Deployment-specific detection patterns from YAML (``ANONYMIZER_CUSTOM_PATTERNS``).

Example::

    patterns:
      - name: order_number
        pattern: '\\b\\d{4}-\\d{4}\\b'
        context_words: [bestellung, bestellnummer, order]
        confidence: 0.85
      - name: customer_number
        pattern: '\\bKD-\\d{6,8}\\b'
        confidence: 0.95

Every pattern becomes a custom recognizer (entity type = ``name`` unless
``entity_type`` is given). Invalid files stop the server: a silently missing
pattern would let identifiers through.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from anonymizer.models import Category

_KEYS = {"name", "entity_type", "pattern", "category", "confidence", "context_words", "languages", "ignore_case"}
_NAME = re.compile(r"[a-z][a-z0-9_]{1,63}")


class PatternError(ValueError):
    pass


def load_custom_patterns(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        raise PatternError(f"custom pattern file not found: {p.name}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise PatternError(f"custom pattern file is not valid YAML: {exc}") from None
    items = data.get("patterns") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise PatternError("custom pattern file needs a non-empty 'patterns' list")
    out: list[dict] = []
    for i, spec in enumerate(items, 1):
        if not isinstance(spec, dict):
            raise PatternError(f"pattern {i} is not a mapping")
        if unknown := set(spec) - _KEYS:
            raise PatternError(f"pattern {i}: unknown keys {sorted(unknown)}")
        name = spec.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise PatternError(f"pattern {i}: 'name' must be lowercase snake_case")
        for key in ("name", "entity_type"):
            if key in spec and not _NAME.fullmatch(str(spec[key])):
                raise PatternError(f"pattern {i}: '{key}' must be lowercase snake_case")
        try:
            re.compile(spec.get("pattern", ""))
        except re.error as exc:
            raise PatternError(f"pattern {i} ({name}): invalid regex: {exc}") from None
        if not spec.get("pattern"):
            raise PatternError(f"pattern {i} ({name}): 'pattern' is required")
        if "category" in spec:
            try:
                Category(spec["category"])
            except ValueError:
                raise PatternError(f"pattern {i} ({name}): unknown category {spec['category']!r}") from None
        conf = float(spec.get("confidence", 0.8))
        if not 0 < conf <= 1:
            raise PatternError(f"pattern {i} ({name}): confidence must be in (0, 1]")
        out.append({**spec, "confidence": conf, "context_words": list(spec.get("context_words") or []),
                    "languages": tuple(spec.get("languages") or ())})
    return out
