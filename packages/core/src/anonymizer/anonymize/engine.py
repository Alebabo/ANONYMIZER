"""Anonymization engine.

Applies one method per detection, keeps the rest of the text byte-identical
and returns the transformed text plus metadata. The result never contains
the re-identification mapping; reversible methods write it to a vault.

Safety net (on by default):

1. *Sweep*: further occurrences of a transformed value that the detector
   missed (any case, also wrapped across a line break) get the same
   replacement.
2. *Leak check*: after transformation, every transformed original value is
   searched in the output (case-insensitive). Hits are reported in
   ``AnonymizationResult.leaks`` and ``strict`` mode raises.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from contextlib import nullcontext
from enum import Enum

from pydantic import BaseModel, Field

from anonymizer.anonymize.transforms import DEFAULT_MASK_KEEP, generalize, mask
from anonymizer.models import INNER_WS, Detection, EntityType as E, ScanResult, make_detection
from anonymizer.vault import InMemoryVault, Vault, VaultError, VaultKey, normalize


class Method(str, Enum):
    KEEP = "keep"
    REDACT = "redact"              # Max Mustermann -> [REDACTED]
    REPLACE = "replace"            # Max Mustermann -> PERSON_001 (numbered per occurrence, no linkage)
    PSEUDONYMIZE = "pseudonymize"  # same entity -> same placeholder (reversible with a vault)
    GENERALIZE = "generalize"      # 15.03.1985 -> 1985
    MASK = "mask"                  # DE89 3704 ... -> DE89 **** **** **** **30 00
    TOKENIZE = "tokenize"          # opaque random token, reversible via vault


REVERSIBLE = {Method.PSEUDONYMIZE, Method.TOKENIZE}

DEFAULT_METHODS: dict[str, Method] = {
    E.PERSON: Method.PSEUDONYMIZE, E.ORGANIZATION: Method.PSEUDONYMIZE, E.EMAIL: Method.PSEUDONYMIZE,
    E.PHONE: Method.PSEUDONYMIZE, E.ADDRESS: Method.PSEUDONYMIZE, E.CASE_NUMBER: Method.PSEUDONYMIZE,
    E.LOCATION: Method.PSEUDONYMIZE,
    E.IBAN: Method.REDACT, E.CREDIT_CARD: Method.REDACT, E.BIC: Method.REDACT, E.TAX_ID: Method.REDACT,
    E.TAX_NUMBER: Method.REDACT, E.SOCIAL_SECURITY_NUMBER: Method.REDACT, E.VAT_ID: Method.REDACT,
    E.DATE_OF_BIRTH: Method.GENERALIZE, E.DATE: Method.KEEP, E.MONEY: Method.KEEP,
    E.HEALTH_DATA: Method.REDACT, E.BIOMETRIC_DATA: Method.REDACT, E.SPECIAL_CATEGORY: Method.REDACT,
    E.CRIMINAL_RECORD: Method.REDACT,
    E.COURT: Method.KEEP, E.LEGAL_CITATION: Method.KEEP,
    E.PRIVILEGE_MARKER: Method.KEEP, E.BUSINESS_SECRET_MARKER: Method.KEEP,
}

ROLE_LABELS_DE = {
    "client": "Mandant", "accused": "Beschuldigte/r", "plaintiff": "Kläger/in", "defendant": "Beklagte/r",
    "witness": "Zeuge/Zeugin", "injured_party": "Geschädigte/r", "counsel": "Rechtsanwalt/-anwältin",
    "judge": "Richter/in", "applicant": "Antragsteller/in", "respondent": "Antragsgegner/in",
    "employee": "Arbeitnehmer/in", "employer": "Arbeitgeber/in", "decedent": "Erblasser/in",
}
ROLE_LABELS_EN = {k: k.replace("_", " ") for k in ROLE_LABELS_DE}

# Placeholder grammar used by restore(): PERSON_001, CASE_NUMBER_012, TKN_3f9a0c1b2d4e
PLACEHOLDER_RE = re.compile(r"\b(?:[A-Z]+(?:_[A-Z]+)*_\d{3,}|TKN_[0-9a-f]{12})\b")


class LeakError(RuntimeError):
    pass


class AnonymizerConfig(BaseModel):
    default_method: Method = Method.REDACT  # for unknown/custom types: fail closed
    methods: dict[str, Method] = Field(default_factory=dict)  # merged over DEFAULT_METHODS
    redaction_text: str = "[REDACTED]"
    redaction_with_type: bool = False      # [REDACTED:IBAN]
    include_role: bool = False             # PERSON_001 (Mandant)
    mask_keep: dict[str, tuple[int, int]] = Field(default_factory=lambda: dict(DEFAULT_MASK_KEEP))
    mask_char: str = "*"
    sweep: bool = True
    strict: bool = True                    # raise LeakError on residual original values

    def method_for(self, entity_type: str) -> Method:
        return self.methods.get(entity_type) or DEFAULT_METHODS.get(entity_type) or self.default_method


class Transformation(BaseModel):
    detection_id: str
    entity_type: str
    method: Method
    start: int          # offsets in the original text
    end: int
    out_start: int      # offsets in the transformed text
    out_end: int
    replacement: str
    swept: bool = False  # added by the sweep, not by the detector
    attributes: dict[str, str] = Field(default_factory=dict)


class AnonymizationResult(BaseModel):
    """Transformed text plus metadata. Contains no original values beyond
    what the chosen methods intentionally keep (e.g. masked suffixes)."""

    text: str
    transformations: list[Transformation]
    namespace: str | None
    reversible: bool
    leaks: list[str] = Field(default_factory=list)  # detection ids whose value still appears


class OpenAnonymizer:
    def __init__(self, config: AnonymizerConfig | None = None, vault: Vault | None = None) -> None:
        self.config = config or AnonymizerConfig()
        self.vault = vault

    # ------------------------------------------------------------------
    def anonymize(
        self,
        text: str,
        scan: ScanResult | list[Detection],
        plan: dict[str, Method] | None = None,
        namespace: str | None = None,
        language: str | None = None,
    ) -> AnonymizationResult:
        """Transform ``text``.

        ``plan`` maps detection ids to methods and wins over the per-type
        defaults (the policy engine produces it). Reversible methods need a
        vault and a namespace; without them, pseudonyms are still consistent
        within this call but cannot be restored.
        """
        detections = scan.detections if isinstance(scan, ScanResult) else list(scan)
        lang = language or (scan.language if isinstance(scan, ScanResult) else "de")
        plan = plan or {}
        methods = {d.id: plan.get(d.id, self.config.method_for(d.entity_type)) for d in detections}

        needs_vault = any(m in REVERSIBLE for m in methods.values())
        reversible = needs_vault and self.vault is not None and namespace is not None
        if needs_vault and self.vault is not None and namespace is None:
            raise VaultError("a namespace is required when a vault is configured")
        vault: Vault = self.vault if reversible else InMemoryVault(VaultKey.generate())
        ns = namespace if reversible else "ephemeral"

        canonical = self._canonical_values(detections)
        active = [d for d in detections if methods[d.id] != Method.KEEP]
        if self.config.sweep:
            swept = self._sweep(text, detections, active)
            for d in swept:
                methods[d.id] = methods[d.attributes["swept_from"]]
                canonical[d.id] = canonical[d.attributes["swept_from"]]
            active += swept

        counters: dict[str, int] = {}
        replacements: dict[str, str] = {}
        # One vault write for the whole document instead of one per new value.
        with getattr(vault, "batch", nullcontext)():
            for d in sorted(active, key=lambda x: x.start):
                replacements[d.id] = self._replacement(d, methods[d.id], canonical[d.id], vault, ns, counters, lang)

        out, transformations = self._apply(text, active, methods, replacements)
        kept = [d.text for d in detections if methods[d.id] == Method.KEEP]
        leaks = self._leaks(out, active, kept)
        if leaks and self.config.strict:
            raise LeakError(f"{len(leaks)} original value(s) still present after anonymization")
        return AnonymizationResult(text=out, transformations=transformations,
                                   namespace=namespace if reversible else None, reversible=reversible, leaks=leaks)

    # ------------------------------------------------------------------
    @staticmethod
    def _canonical_values(detections: list[Detection]) -> dict[str, str]:
        """Value used as pseudonym key: the longest mention of the same ref
        ("Mustermann" -> "Max Mustermann"), otherwise the value itself."""
        longest: dict[str, str] = {}
        for d in detections:
            ref = d.attributes.get("ref")
            if ref and len(d.text) > len(longest.get(ref, "")):
                longest[ref] = d.text
        return {d.id: longest.get(d.attributes.get("ref", ""), d.text) for d in detections}

    @staticmethod
    def _sweep(text: str, detections: list[Detection], active: list[Detection]) -> list[Detection]:
        # Non-overlapping covered spans, kept sorted so the overlap test is a
        # bisect instead of a scan over every span.
        covered = sorted((d.start, d.end) for d in detections)
        # Pre-filter: a value can only have a free occurrence if one of its
        # words occurs more often in the text than inside detected spans.
        folded = text.casefold()
        inside = "\x00".join(d.text for d in detections).casefold()
        extra: list[Detection] = []
        done: set[str] = set()
        for d in active:
            # The first detection of a value claims all its free occurrences,
            # so repeated values need no second pass over the text.
            key = normalize(d.text)
            if len(key) < 3 or key in done:
                continue
            done.add(key)
            tokens = d.text.split()
            probe = max(tokens, key=len).casefold()
            if "\x00" not in probe and folded.count(probe) == inside.count(probe):
                continue
            # Same tolerance as the leak check (case, wrapped lines): what the
            # leak check would reject is replaced here instead.
            pattern = INNER_WS.join(re.escape(token) for token in tokens)
            # Same word boundaries as the leak check: "Temu" in "Temu-Bestellung" is an occurrence too.
            for m in re.finditer(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE):
                span = (m.start(), m.end())
                i = bisect_right(covered, span)
                if (i and covered[i - 1][1] > span[0]) or (i < len(covered) and covered[i][0] < span[1]):
                    continue
                covered.insert(i, span)
                det = make_detection(d.entity_type, d.category, span[0], span[1], m.group(0), d.confidence, "sweep",
                                     attributes={**d.attributes, "swept_from": d.id})
                extra.append(det)
        return extra

    def _placeholder_prefix(self, entity_type: str) -> str:
        return re.sub(r"[^A-Z]+", "_", entity_type.upper()).strip("_") or "ENTITY"

    def _replacement(self, d: Detection, method: Method, canonical: str, vault: Vault, ns: str,
                     counters: dict[str, int], lang: str) -> str:
        cfg = self.config
        prefix = self._placeholder_prefix(d.entity_type)
        if method == Method.REDACT:
            return f"[REDACTED:{prefix}]" if cfg.redaction_with_type else cfg.redaction_text
        if method == Method.REPLACE:
            counters[prefix] = counters.get(prefix, 0) + 1
            return f"{prefix}_{counters[prefix]:03d}"
        if method == Method.PSEUDONYMIZE:
            placeholder = vault.pseudonym(ns, d.entity_type, canonical, prefix)
            role = d.attributes.get("role")
            if cfg.include_role and role:
                label = (ROLE_LABELS_DE if lang == "de" else ROLE_LABELS_EN).get(role, role)
                return f"{placeholder} ({label})"
            return placeholder
        if method == Method.TOKENIZE:
            return vault.token(ns, d.entity_type, canonical)
        if method == Method.MASK:
            return mask(d.text, d.entity_type, cfg.mask_keep, cfg.mask_char)
        if method == Method.GENERALIZE:
            general = generalize(d.text, d.entity_type)
            return general if general is not None else f"[{prefix}]"
        raise ValueError(f"unsupported method {method}")

    @staticmethod
    def _apply(text: str, active: list[Detection], methods: dict[str, Method],
               replacements: dict[str, str]) -> tuple[str, list[Transformation]]:
        parts: list[str] = []
        transformations: list[Transformation] = []
        cursor = 0
        out_len = 0
        for d in sorted(active, key=lambda x: x.start):
            if d.start < cursor:  # defensive: overlapping input
                continue
            parts.append(text[cursor:d.start])
            out_len += d.start - cursor
            rep = replacements[d.id]
            transformations.append(Transformation(
                detection_id=d.id, entity_type=d.entity_type, method=methods[d.id], start=d.start, end=d.end,
                out_start=out_len, out_end=out_len + len(rep), replacement=rep,
                swept=d.recognizer == "sweep",
                attributes={k: v for k, v in d.attributes.items() if k in ("role", "ref")},
            ))
            parts.append(rep)
            out_len += len(rep)
            cursor = d.end
        parts.append(text[cursor:])
        return "".join(parts), transformations

    @staticmethod
    def _leaks(out: str, active: list[Detection], kept: list[str] | None = None) -> list[str]:
        folded = normalize(out)
        # Values kept on purpose stay readable and may contain a replaced value: the city "Köln" of an address
        # inside the court name "Arbeitsgericht Köln". Such an occurrence is not a leak.
        for value in sorted({normalize(k) for k in kept or [] if k}, key=len, reverse=True):
            folded = folded.replace(value, " " * len(value))
        verdict: dict[str, bool] = {}  # one search per distinct value
        leaks = []
        for d in active:
            value = normalize(d.text)
            if value not in verdict:
                # Substring test first: it is far cheaper than the regex and
                # almost always negative.
                verdict[value] = (len(value) >= 3 and value in folded
                                  and re.search(rf"(?<!\w){re.escape(value)}(?!\w)", folded) is not None)
            if verdict[value]:
                leaks.append(d.id)
        return leaks


# ----------------------------------------------------------------------
class RestoreResult(BaseModel):
    text: str
    restored: int
    unresolved: list[str]  # placeholder-shaped strings without a vault entry


def restore(text: str, vault: Vault, namespace: str) -> RestoreResult:
    """Replace placeholders/tokens (e.g. in an LLM answer) with original values.

    Must only run inside the trusted boundary for authorised users. Unknown
    placeholder-shaped strings (e.g. invented by the model) stay unchanged
    and are reported.
    """
    restored = 0
    unresolved: list[str] = []

    def sub(m: re.Match[str]) -> str:
        nonlocal restored
        original = vault.resolve(namespace, m.group(0))
        if original is None:
            unresolved.append(m.group(0))
            return m.group(0)
        restored += 1
        return original

    return RestoreResult(text=PLACEHOLDER_RE.sub(sub, text), restored=restored, unresolved=unresolved)
