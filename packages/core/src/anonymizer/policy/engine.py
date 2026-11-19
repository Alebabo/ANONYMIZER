"""Deterministic policy evaluation.

Per entity:
  1. collect matching rules (all conditions AND, list values OR, destination aware)
  2. winner = highest priority; tie -> most restrictive action; tie -> rule order
  3. no match -> default_action
  4. critical floor: a critical entity never leaves unchanged to an external
     destination unless the winning rule sets allow_critical
  5. local_only on a local destination -> allow (it is processed locally)

Per document:
  outcome = most restrictive of (entity gate actions, document rules,
  review_uncertain); block > local_only > review > allow.

No LLM and no randomness is involved; the same inputs give the same decision.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from anonymizer.anonymize import Method
from anonymizer.classify import DocumentClassification, EntityClassification, RiskLevel
from anonymizer.models import Detection
from anonymizer.policy.model import ACTION_TO_METHOD, GATE_ACTIONS, Action, DocumentRule, Policy, Rule


class Outcome(str, Enum):
    ALLOW = "allow"            # send the transformed text
    REVIEW = "review"          # hold for human approval
    LOCAL_ONLY = "local_only"  # only a local model may process it
    BLOCK = "block"            # must not be sent

    @property
    def severity(self) -> int:
        return list(Outcome).index(self)


_GATE_TO_OUTCOME = {Action.REVIEW: Outcome.REVIEW, Action.LOCAL_ONLY: Outcome.LOCAL_ONLY, Action.BLOCK: Outcome.BLOCK}


class EntityDecision(BaseModel):
    detection_id: str
    entity_type: str
    risk: RiskLevel
    action: Action
    method: Method
    rule_id: str | None            # None = default_action
    overruled: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    """Auditable result. Contains ids, actions and reasons, no raw values."""

    outcome: Outcome
    policy: str            # name@vN
    policy_hash: str
    destination: str
    dry_run: bool = False
    entities: list[EntityDecision]
    document_rules: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @property
    def plan(self) -> dict[str, Method]:
        """Detection id -> anonymization method, for :class:`anonymizer.anonymize.OpenAnonymizer`."""
        return {e.detection_id: e.method for e in self.entities}

    @property
    def may_send(self) -> bool:
        return self.outcome == Outcome.ALLOW or (self.outcome == Outcome.LOCAL_ONLY and self.destination == "local")


def _rule_matches(rule: Rule, det: Detection, ent: EntityClassification, doc_signals: set[str],
                  destination: str) -> bool:
    if rule.destinations and destination not in rule.destinations:
        return False
    if rule.entity and det.entity_type not in rule.entity:
        return False
    if rule.category and det.category.value not in rule.category:
        return False
    if rule.risk and ent.risk not in rule.risk:
        return False
    if rule.min_risk and ent.risk < rule.min_risk:
        return False
    if rule.role and det.attributes.get("role") not in rule.role:
        return False
    if rule.signals and not set(rule.signals) & set(det.signals):
        return False
    if rule.document_signals and not set(rule.document_signals) & doc_signals:
        return False
    if rule.max_confidence is not None and det.confidence > rule.max_confidence:
        return False
    return True


def _doc_rule_matches(rule: DocumentRule, doc: DocumentClassification, entity_types: set[str],
                      destination: str) -> bool:
    if rule.destinations and destination not in rule.destinations:
        return False
    if rule.risk and doc.risk not in rule.risk:
        return False
    if rule.min_risk and doc.risk < rule.min_risk:
        return False
    if rule.signals and not set(rule.signals) & set(doc.signals):
        return False
    if rule.entity_present and not set(rule.entity_present) & entity_types:
        return False
    return True


class PolicyEngine:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def evaluate(
        self,
        detections: list[Detection],
        classification: DocumentClassification,
        destination: str = "external",
        dry_run: bool = False,
    ) -> PolicyDecision:
        if destination not in ("external", "local"):
            raise ValueError("destination must be 'external' or 'local'")
        p = self.policy
        by_id = {d.id: d for d in detections}
        doc_signals = set(classification.signals)
        order = {r.id: i for i, r in enumerate(p.rules)}

        entities: list[EntityDecision] = []
        for ent in classification.entities:
            det = by_id[ent.detection_id]
            matching = [r for r in p.rules if _rule_matches(r, det, ent, doc_signals, destination)]
            matching.sort(key=lambda r: (-r.priority, -r.action.severity, order[r.id]))
            reasons: list[str] = []
            if matching:
                winner = matching[0]
                action, rule_id = winner.action, winner.id
                reasons.append(f"{rule_id}: {winner.description or action.value}")
                overruled = [r.id for r in matching[1:] if r.action != action]
                if overruled:
                    reasons.append(f"overrules {', '.join(overruled)} (priority, then most restrictive)")
            else:
                winner, action, rule_id, overruled = None, p.default_action, None, []
                reasons.append(f"default_action: {action.value}")

            if (p.critical_floor and destination == "external" and ent.risk == RiskLevel.CRITICAL
                    and action == Action.ALLOW and not (winner and winner.allow_critical)):
                action = p.critical_floor_action
                reasons.append(f"critical floor: critical data is not sent unchanged -> {action.value}")

            if action == Action.LOCAL_ONLY and destination == "local":
                action = Action.ALLOW
                reasons.append("local_only satisfied by local destination")

            entities.append(EntityDecision(
                detection_id=ent.detection_id, entity_type=ent.entity_type, risk=ent.risk, action=action,
                method=ACTION_TO_METHOD[action], rule_id=rule_id, overruled=overruled, reasons=reasons,
            ))

        outcome = Outcome.ALLOW
        reasons: list[str] = []
        for e in entities:
            if e.action in GATE_ACTIONS:
                o = _GATE_TO_OUTCOME[e.action]
                if o.severity > outcome.severity:
                    outcome = o
                reasons.append(f"{e.entity_type} ({e.detection_id}) -> {e.action.value}")

        matched_doc_rules: list[str] = []
        entity_types = {d.entity_type for d in detections}
        doc_rules = sorted((r for r in p.document_rules if _doc_rule_matches(r, classification, entity_types, destination)),
                           key=lambda r: (-r.priority, -r.action.severity))
        for r in doc_rules:
            matched_doc_rules.append(r.id)
            if r.action in GATE_ACTIONS:
                o = _GATE_TO_OUTCOME[r.action]
                if o.severity > outcome.severity:
                    outcome = o
                reasons.append(f"{r.id}: {r.description or r.action.value}")

        if p.review_uncertain and classification.needs_review and outcome.severity < Outcome.REVIEW.severity:
            outcome = Outcome.REVIEW
            reasons.append("classification flagged uncertain entities (review_uncertain)")

        if outcome == Outcome.LOCAL_ONLY and destination == "local":
            reasons.append("local_only satisfied by local destination")

        if not reasons:
            reasons.append("no gate action triggered")

        return PolicyDecision(
            outcome=outcome, policy=p.ref, policy_hash=p.content_hash, destination=destination, dry_run=dry_run,
            entities=entities, document_rules=matched_doc_rules, reasons=reasons,
        )


class DecisionChange(BaseModel):
    detection_id: str
    entity_type: str
    before: Action
    after: Action


class DecisionDiff(BaseModel):
    outcome_before: Outcome
    outcome_after: Outcome
    changes: list[DecisionChange]


def diff_decisions(before: PolicyDecision, after: PolicyDecision) -> DecisionDiff:
    """Compare a live decision with a dry-run decision of a candidate policy."""
    old = {e.detection_id: e for e in before.entities}
    changes = [
        DecisionChange(detection_id=e.detection_id, entity_type=e.entity_type, before=old[e.detection_id].action,
                       after=e.action)
        for e in after.entities if e.detection_id in old and old[e.detection_id].action != e.action
    ]
    return DecisionDiff(outcome_before=before.outcome, outcome_after=after.outcome, changes=changes)
