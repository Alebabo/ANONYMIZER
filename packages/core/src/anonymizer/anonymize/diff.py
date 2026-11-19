"""Original vs. anonymized comparison for review UIs.

The diff needs the original text, which the anonymization result does not
hold on purpose. Build it only inside the protected environment, for users
allowed to see originals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from anonymizer.anonymize.engine import AnonymizationResult


class DiffSegment(BaseModel):
    kind: Literal["equal", "changed"]
    original: str
    anonymized: str
    entity_type: str | None = None
    method: str | None = None


def build_diff(original_text: str, result: AnonymizationResult) -> list[DiffSegment]:
    segments: list[DiffSegment] = []
    cursor = 0
    for t in sorted(result.transformations, key=lambda x: x.start):
        if t.start > cursor:
            same = original_text[cursor:t.start]
            segments.append(DiffSegment(kind="equal", original=same, anonymized=same))
        segments.append(DiffSegment(kind="changed", original=original_text[t.start:t.end], anonymized=t.replacement,
                                    entity_type=t.entity_type, method=t.method.value))
        cursor = t.end
    if cursor < len(original_text):
        rest = original_text[cursor:]
        segments.append(DiffSegment(kind="equal", original=rest, anonymized=rest))
    return segments
