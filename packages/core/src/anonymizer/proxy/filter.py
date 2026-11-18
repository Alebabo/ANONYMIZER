"""Protect upstream tool results before they reach the MCP client.

* Text blocks: JSON (object/array) is protected value by value, keys stay readable; other text as a whole.
* Field names act as hints (``email``, ``vorname``, ``iban``, ...): such values are treated as that entity
  even if detection finds nothing in them (fail closed for short database values).
* ``structured_content`` is protected the same way.
* Non-text content (images, audio, binary resources, resource links) is withheld in enforce mode.
* Observe mode runs the same analysis but returns the original result. Only for test data or after approval.

The report keeps metadata only: entity types, counts and field paths (array indices collapsed). No values.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import mcp_types as types

from anonymizer.detect import detect_language
from anonymizer.detect.ner import ID_LIKE
from anonymizer.models import DEFAULT_CATEGORIES, Category, ScanResult, make_detection
from anonymizer.pipeline import Pipeline, ProtectResult
from anonymizer.proxy.config import norm_key
from anonymizer.tracing import Trace, merge_traces, trace_from_protect

WITHHELD = "[WITHHELD]"
_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,48}$")
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")  # column/table/status names: no NER (over-redaction)
# Values learned from hinted fields are searched for in free text (e.g. a surname from a customer table
# inside a ticket). Only these types, only values of at least this length.
_LEARN_TYPES = {"person", "email", "phone", "iban", "address", "tax_id", "social_security_number"}
_LEARN_MIN = 3
_LEARN_MAX = 50_000


class KnownValues:
    """Raw values seen in hinted fields of one upstream. In memory only, like the in-memory vault."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self._pattern: re.Pattern | None = None
        self._lock = threading.Lock()  # results are filtered in worker threads, several calls at a time

    def add(self, value: str, entity_type: str) -> None:
        for part in ([value] if entity_type != "person" else value.split()):
            part = part.strip(" ,;")
            if len(part) < _LEARN_MIN or part in self.values:
                continue
            with self._lock:
                if part not in self.values and len(self.values) < _LEARN_MAX:
                    self.values[part] = entity_type
                    self._pattern = None

    def find(self, text: str) -> list[tuple[int, int, str]]:
        with self._lock:
            if not self.values:
                return []
            if self._pattern is None:
                alts = sorted(self.values, key=len, reverse=True)
                self._pattern = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, alts)) + r")(?!\w)")
            pattern, values = self._pattern, self.values
        return [(m.start(), m.end(), values[m.group(1)]) for m in pattern.finditer(text)]


@dataclass
class FilterReport:
    parts: list[Trace] = field(default_factory=list)
    fields: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    values: int = 0               # leaves analysed
    changed: int = 0              # leaves changed (enforce) or that would change (observe)
    withheld: int = 0             # leaves withheld by the policy
    hinted: int = 0               # leaves treated as an entity because of the field name
    learned: int = 0              # matches of values learned from hinted fields in free text
    non_text: int = 0             # non-text blocks withheld / passed
    warnings: list[str] = field(default_factory=list)

    def trace(self, **extra: Any) -> Trace:
        t = merge_traces("/mcp/proxy", self.parts, **extra) if self.parts else Trace(
            route="/mcp/proxy", outcome="allow", allowed=True, risk="low", **extra)
        t.fields = {p: dict(c) for p, c in sorted(self.fields.items())}
        t.warnings = sorted(set(t.warnings) | set(self.warnings))
        return t


class ResultFilter:
    def __init__(self, pipeline: Pipeline, destination: str, namespace: str | None, *, observe: bool,
                 hints: dict[str, str], language: str | None = None, max_chars: int = 500_000,
                 known: KnownValues | None = None, rules: Any = None) -> None:
        self.pipeline = pipeline
        self.destination = destination
        self.namespace = namespace
        self.observe = observe
        self.hints = hints
        self.language = language
        self.max_chars = max_chars
        self.known = known if known is not None else KnownValues()
        if rules is None:  # rules-only detector for keys and identifiers
            from anonymizer.detect import Detector, DetectorConfig

            cfg = pipeline.detector.config
            rules = Detector(DetectorConfig(custom_entities=list(cfg.custom_entities), enable_ner=False))
        self.rules = rules
        self._key_cache: dict[str, bool] = {}
        self._leaf_cache: dict[tuple, str] = {}
        self._seen: set[tuple] = set()
        self._lang = language or "de"

    # -- entry point -------------------------------------------------------------------------
    def apply(self, result: types.CallToolResult) -> tuple[types.CallToolResult, FilterReport]:
        report = FilterReport()
        self._leaf_cache, self._seen = {}, set()
        # One language per result, so the text and the structured copy of the same data are treated alike.
        sample = " ".join(c.text for c in result.content if isinstance(c, types.TextContent))[:5000]
        if not sample.strip() and result.structured_content is not None:
            sample = json.dumps(result.structured_content, ensure_ascii=False)[:5000]
        self._lang = self.language or detect_language(sample)
        # Everything that is analysed counts: text blocks, embedded text resources and structured content.
        size = sum(len(getattr(c, "text", None) or getattr(getattr(c, "resource", None), "text", None) or "")
                   for c in result.content)
        if result.structured_content is not None:
            size += len(json.dumps(result.structured_content, ensure_ascii=False))
        if size > self.max_chars:
            report.warnings.append(f"result larger than {self.max_chars} characters")
            if self.observe:  # passes through anyway; analysing it would only cost time
                return result, report
            if not self.observe:
                report.withheld += 1
                return types.CallToolResult(content=[_text(f"[OpenAnonymizer: result withheld, larger than "
                                                           f"{self.max_chars} characters]")],
                                            is_error=result.is_error), report
        for c in result.content:
            if isinstance(c, types.TextContent) and c.text.strip()[:1] in "{[":
                try:
                    self._learn(json.loads(c.text), None)
                except ValueError:
                    pass
        if result.structured_content is not None:
            self._learn(result.structured_content, None)
        content = [self._block(c, report) for c in result.content]
        structured = result.structured_content
        if structured is not None:
            # Often a copy of the text blocks: values already counted there are not counted again.
            structured = self._walk(structured, "$", None, report, self._lang)
        if self.observe:
            return result, report
        return types.CallToolResult(content=content, structured_content=structured, is_error=result.is_error), report

    # -- content blocks ----------------------------------------------------------------------
    def _block(self, block: Any, report: FilterReport) -> Any:
        if isinstance(block, types.TextContent):
            return types.TextContent(type="text", text=self._text_payload(block.text, "$", report))
        if isinstance(block, types.EmbeddedResource) and isinstance(block.resource, types.TextResourceContents):
            res = block.resource
            uri = self._leaf(str(res.uri), "$resource.uri", None, report, self._lang)
            text = self._text_payload(res.text, "$resource", report)
            if uri == WITHHELD:
                return _text(f"[OpenAnonymizer: embedded resource withheld]\n{text}")
            return types.EmbeddedResource(type="resource", resource=types.TextResourceContents(
                uri=uri, mime_type=res.mime_type, text=text))
        report.non_text += 1
        kind = getattr(block, "type", "unknown")
        if self.observe:
            report.warnings.append(f"non-text content passed unchecked ({kind})")
            return block
        report.warnings.append(f"non-text content withheld ({kind})")
        return _text(f"[OpenAnonymizer: {kind} content withheld; only text content is filtered]")

    def _text_payload(self, text: str, path: str, report: FilterReport) -> str:
        stripped = text.strip()
        if stripped[:1] in "{[":
            try:
                data = json.loads(stripped)
            except ValueError:
                data = None
            if isinstance(data, (dict, list)):
                out = self._walk(data, path, None, report, self._lang)
                return json.dumps(out, ensure_ascii=False, indent=2)
        out = self._leaf(text, path, None, report, self._lang, block=True)
        return out

    # -- JSON --------------------------------------------------------------------------------
    def _walk(self, value: Any, path: str, key: str | None, report: FilterReport, lang: str) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                k = str(k)
                safe = self._safe_key(k)
                child = f"{path}.{k}" if safe else f"{path}.*"
                new_key = k if safe else self._leaf(k, f"{path}.<key>", None, report, lang)
                if new_key in out:  # two keys collapsed onto the same placeholder
                    new_key = f"{new_key}#{len(out)}"
                out[new_key] = self._walk(v, child, k if safe else None, report, lang)
            return out
        if isinstance(value, list):
            return [self._walk(v, f"{path}[]", key, report, lang) for v in value]
        if isinstance(value, str):
            return self._leaf(value, path, key, report, lang)
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and key and norm_key(key) in self.hints:
            out = self._leaf(str(value), path, key, report, lang)
            return value if out == str(value) else out
        if isinstance(value, int) and abs(value) >= 10 ** 11:
            # Long numbers can be card or account numbers: same rules as for a string of digits.
            out = self._leaf(str(value), path, key, report, lang)
            return value if out == str(value) else out
        return value

    def _learn(self, value: Any, key: str | None) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                self._learn(v, str(k))
        elif isinstance(value, list):
            for v in value:
                self._learn(v, key)
        elif isinstance(value, (str, int)) and not isinstance(value, bool) and key:
            hint = self.hints.get(norm_key(key))
            if hint in _LEARN_TYPES:
                self.known.add(str(value), hint)

    def _safe_key(self, key: str) -> bool:
        if key not in self._key_cache:
            ok = norm_key(key) in self.hints or (
                bool(_SAFE_KEY.match(key)) and sum(ch.isdigit() for ch in key) < 4
                and not self.rules.scan(key, "en").detections and key not in self.known.values)
            self._key_cache[key] = ok
        return self._key_cache[key]

    # -- one value ---------------------------------------------------------------------------
    def _leaf(self, text: str, path: str, key: str | None, report: FilterReport, lang: str,
              block: bool = False) -> str:
        if not text or not text.strip():
            return text
        hint = self.hints.get(norm_key(key)) if key else None
        cache_key = (text, hint, lang, block)
        if cache_key in self._leaf_cache:
            return self._leaf_cache[cache_key]
        # Same value again in another shape (text block vs. structured copy): protect it, count it once.
        seen = (text, hint, lang)
        out = self._leaf_uncached(text, path, hint, FilterReport() if seen in self._seen else report, lang, block)
        self._seen.add(seen)
        self._leaf_cache[cache_key] = out
        return out

    def _leaf_uncached(self, text: str, path: str, hint: str | None, report: FilterReport, lang: str,
                       block: bool) -> str:
        report.values += 1
        identifier = not hint and (bool(_IDENTIFIER.match(text)) or text.isdigit() or bool(ID_LIKE.fullmatch(text))
                                   ) and text not in self.known.values
        scan = (self.rules if identifier else self.pipeline.detector).scan(text, lang)
        if hint and not _covers(scan, len(text), hint):
            # The column name wins over another type (e.g. NER reads a surname as an organisation), so the
            # value gets the same placeholder here and in free text. Checksum-validated values keep their type.
            det = make_detection(hint, DEFAULT_CATEGORIES.get(hint, Category.PERSONAL_DATA), 0, len(text), text,
                                 0.99, "field_hint", attributes={"field_hint": "1"})
            scan = ScanResult(language=scan.language, detections=[det], signals=scan.signals, warnings=scan.warnings)
            report.hinted += 1
        elif not hint:
            # A value learned from a hinted column keeps that column's type in free text. It replaces detections
            # that lie inside it and are not checksum-validated (e.g. NER calling the surname an organisation);
            # a wider detection around it (a full name) is kept.
            dets, extra = list(scan.detections), []
            for a, b, t in self.known.find(text):
                overlap = [d for d in dets if d.start < b and a < d.end]
                if any(d.start < a or d.end > b or d.validated is True for d in overlap):
                    continue
                if any(d.entity_type == t and d.start == a and d.end == b for d in overlap):
                    continue
                dets = [d for d in dets if d not in overlap]
                extra.append(make_detection(t, DEFAULT_CATEGORIES.get(t, Category.PERSONAL_DATA), a, b, text[a:b],
                                            0.95, "known_value"))
            if extra:
                scan = ScanResult(language=scan.language, detections=sorted(dets + extra, key=lambda d: d.start),
                                  signals=scan.signals, warnings=scan.warnings)
                report.learned += len(extra)
        if not scan.detections and not scan.signals:
            return text
        result: ProtectResult = self.pipeline.protect_scan(text, scan, self.destination, self.namespace,
                                                           dry_run=self.observe)
        report.parts.append(trace_from_protect("/mcp/proxy", result, original=text, label=path))
        report.fields[path].update(d.entity_type for d in scan.detections)
        if scan.detections:
            report.changed += 1
        if not result.decision.may_send:
            report.withheld += 1
            if self.observe:
                return text
            return (f"[OpenAnonymizer: content withheld by policy ({result.decision.outcome.value}): "
                    f"{'; '.join(result.decision.reasons)}]") if block else WITHHELD
        if self.observe or result.text is None:
            return text
        return result.text



def _covers(scan: ScanResult, length: int, hint: str) -> bool:
    """A detection of the hinted type, or a checksum-validated one, already spans (almost) the whole value."""
    return any(d.end - d.start >= length * 0.8 and (d.entity_type == hint or d.validated is True)
               for d in scan.detections)


def _text(text: str) -> types.TextContent:
    return types.TextContent(type="text", text=text)
