"""Simple policy editing: one action per entity type.

A rule that only names entity types (no other condition) is "simple"; every other rule is kept as it is.
A change moves the type out of its simple rule into one rule per action (``editor_<action>``). Mirrors
``lib/policy-edit.ts`` in the dashboard, which builds the version it saves the same way.
"""

from __future__ import annotations

from anonymizer.policy.model import Action, Policy, Rule

_CONDITIONS = ("category", "risk", "min_risk", "role", "signals", "document_signals", "max_confidence", "destinations")


def is_simple(rule: Rule) -> bool:
    return bool(rule.entity) and all(getattr(rule, k) is None for k in _CONDITIONS) \
        and not rule.priority and not rule.allow_critical


def entity_actions(policy: Policy) -> dict[str, Action]:
    """Action per entity type from the simple rules (the more restrictive one wins)."""
    out: dict[str, Action] = {}
    for rule in filter(is_simple, policy.rules):
        for e in rule.entity or []:
            if e not in out or rule.action.severity > out[e].severity:
                out[e] = rule.action
    return out


def apply_changes(policy: Policy, changes: dict[str, Action | None], default_action: Action | None = None) -> Policy:
    """Next version with the given action per type (``None``: follow ``default_action``)."""
    current = entity_actions(policy)
    changed = {t: a for t, a in changes.items() if current.get(t) != a}
    rules = [r.model_copy(update={"entity": [e for e in r.entity or [] if e not in changed]}) if is_simple(r)
             else r.model_copy() for r in policy.rules]
    for t, a in changed.items():
        if a is None:
            continue
        target = next((r for r in rules if r.id == f"editor_{a.value}"), None)
        if target is not None:
            target.entity = [*(target.entity or []), t]
        else:
            rules.append(Rule(id=f"editor_{a.value}", description="Set in the dashboard", entity=[t], action=a))
    rules = [r for r in rules if not (r.entity is not None and not r.entity and all(getattr(r, k) is None for k in _CONDITIONS))]
    return policy.model_copy(update={"version": policy.version + 1, "rules": rules,
                                     "default_action": default_action or policy.default_action})
