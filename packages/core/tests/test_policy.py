import json

import pytest
from pydantic import ValidationError

from anonymizer import scan
from anonymizer.anonymize import Method
from anonymizer.classify import Classifier
from anonymizer.pipeline import Pipeline
from anonymizer.policy import (
    Action, FilePolicyStore, InMemoryPolicyStore, Outcome, Policy, PolicyEngine, PolicyError, builtin_policy,
    diff_decisions,
)

SPEC_POLICY = """
name: legal-default
version: 1
rules:
  - entity: person
    action: pseudonymize
  - entity: iban
    action: redact
  - entity: health_data
    action: block
  - entity: client_secret
    action: block
default_action: allow
"""


def evaluate(policy_yaml_or_obj, text, destination="external", language="de"):
    policy = policy_yaml_or_obj if isinstance(policy_yaml_or_obj, Policy) else Policy.from_yaml(policy_yaml_or_obj)
    result = scan(text, language)
    classification = Classifier().classify_text(text, result)
    return PolicyEngine(policy).evaluate(result.detections, classification, destination), result


def action_for(decision, entity_type):
    return next(e for e in decision.entities if e.entity_type == entity_type)


# --- the spec example ---------------------------------------------------------

def test_spec_policy_example():
    d, _ = evaluate(SPEC_POLICY, "Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00.")
    assert action_for(d, "person").action == Action.PSEUDONYMIZE
    assert action_for(d, "iban").action == Action.REDACT
    assert d.outcome == Outcome.ALLOW and d.may_send


def test_spec_policy_blocks_health_data():
    d, _ = evaluate(SPEC_POLICY, "Herr Max Mustermann leidet an einer Depression.")
    assert action_for(d, "health_data").action == Action.BLOCK
    assert d.outcome == Outcome.BLOCK and not d.may_send


# --- matching & conflicts -------------------------------------------------------

def test_priority_wins_over_order():
    d, _ = evaluate("""
name: p
rules:
  - {id: a, entity: person, action: redact}
  - {id: b, entity: person, action: allow, priority: 5}
default_action: redact
critical_floor: false
""", "Herr Max Mustermann")
    e = action_for(d, "person")
    assert e.action == Action.ALLOW and e.rule_id == "b" and e.overruled == ["a"]


def test_equal_priority_most_restrictive_wins():
    d, _ = evaluate("""
name: p
rules:
  - {id: soft, entity: person, action: pseudonymize}
  - {id: hard, category: personal_data, action: redact}
""", "Herr Max Mustermann")
    assert action_for(d, "person").rule_id == "hard"


def test_conditions_role_signal_and_risk():
    policy = """
name: p
rules:
  - {id: clients, entity: person, role: client, action: tokenize}
  - {id: criminal, entity: person, signals: criminal_proceeding, action: redact, priority: 1}
  - {id: crit, min_risk: critical, action: pseudonymize}
default_action: allow
"""
    d, _ = evaluate(policy, "Unser Mandant Herr Max Mustermann hat geklagt.")
    assert action_for(d, "person").rule_id == "clients"
    d, _ = evaluate(policy, "Im Strafverfahren ist Herr Max Mustermann unser Mandant.")
    assert action_for(d, "person").rule_id == "criminal"


def test_destination_specific_rules_and_local_only():
    policy = builtin_policy()
    text = "Herr Max Mustermann leidet an einer Depression."
    ext, _ = evaluate(policy, text, "external")
    loc, _ = evaluate(policy, text, "local")
    assert ext.outcome == Outcome.LOCAL_ONLY and not ext.may_send
    assert loc.outcome == Outcome.ALLOW and loc.may_send
    assert action_for(loc, "health_data").action == Action.ALLOW


def test_default_action_when_no_rule_matches():
    d, _ = evaluate("name: p\nrules: []\ndefault_action: mask\n", "Mail an max@example.org")
    e = action_for(d, "email")
    assert e.action == Action.MASK and e.rule_id is None and "default_action" in e.reasons[0]


# --- safety floor -----------------------------------------------------------------

def test_critical_floor_prevents_unchanged_critical_data():
    d, _ = evaluate("name: p\ndefault_action: allow\n", "IBAN DE89 3704 0044 0532 0130 00")
    e = action_for(d, "iban")
    assert e.action == Action.PSEUDONYMIZE and any("critical floor" in r for r in e.reasons)


def test_critical_floor_explicit_opt_out_and_local_destination():
    policy = "name: p\nrules:\n  - {entity: iban, action: allow, allow_critical: true}\ndefault_action: allow\n"
    d, _ = evaluate(policy, "IBAN DE89 3704 0044 0532 0130 00")
    assert action_for(d, "iban").action == Action.ALLOW
    d, _ = evaluate("name: p\ndefault_action: allow\n", "IBAN DE89 3704 0044 0532 0130 00", destination="local")
    assert action_for(d, "iban").action == Action.ALLOW


# --- document rules ----------------------------------------------------------------

def test_document_rule_review_for_critical_criminal_matter():
    d, _ = evaluate(builtin_policy(), "Herr Max Mustermann ist unser Mandant im Strafverfahren 123 Js 4567/24.")
    assert d.outcome == Outcome.REVIEW and "criminal_privileged_review" in d.document_rules


def test_document_rule_block_on_critical():
    d, _ = evaluate("name: p\ndocument_rules:\n  - {min_risk: critical, action: block}\ndefault_action: redact\n",
                    "IBAN DE89 3704 0044 0532 0130 00")
    assert d.outcome == Outcome.BLOCK


def test_review_uncertain():
    policy = "name: p\nreview_uncertain: true\ndefault_action: redact\n"
    d, _ = evaluate(policy, "Bitte überweisen Sie auf IBAN DE00 1234 5678 9012 3456 78.")  # failed checksum
    assert d.outcome == Outcome.REVIEW


# --- validation ---------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "name: p\nrules:\n  - {entity: person, action: delete}\n",          # unknown action
    "name: p\nrules:\n  - {entity: person, action: allow, colour: red}\n",  # unknown field
    "name: p\nrules:\n  - {entity: person, action: allow, destinations: cloud}\n",
    "name: p\ndocument_rules:\n  - {action: redact}\n",                     # entity action on document
    "name: p\nrules:\n  - {id: x, entity: a, action: allow}\n  - {id: x, entity: b, action: allow}\n",
    "name: Bad Name\n",
    "name: p\ncritical_floor_action: allow\n",
])
def test_invalid_policies_rejected(bad):
    with pytest.raises(ValidationError):
        Policy.from_yaml(bad)


# --- determinism & audit ------------------------------------------------------------

def test_decision_is_deterministic_and_references_version():
    text = "Unser Mandant Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00, Depression."
    a, _ = evaluate(builtin_policy(), text)
    b, _ = evaluate(builtin_policy(), text)
    assert a.model_dump() == b.model_dump()
    assert a.policy == "legal-default@v1" and a.policy_hash.startswith("sha256:")


def test_decision_contains_no_raw_values():
    d, _ = evaluate(builtin_policy(), "Unser Mandant Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00.")
    dump = json.dumps(d.model_dump(mode="json"))
    assert "Mustermann" not in dump and "DE89" not in dump


def test_plan_maps_to_anonymizer_methods():
    d, _ = evaluate(SPEC_POLICY, "Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00.")
    assert set(d.plan.values()) == {Method.PSEUDONYMIZE, Method.REDACT}


# --- dry run ---------------------------------------------------------------------------

def test_dry_run_diff_between_policies():
    text = "Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00."
    live, result = evaluate(SPEC_POLICY, text)
    candidate = Policy.from_yaml(SPEC_POLICY.replace("entity: iban\n    action: redact", "entity: iban\n    action: block"))
    classification = Classifier().classify_text(text, result)
    dry = PolicyEngine(candidate).evaluate(result.detections, classification, dry_run=True)
    diff = diff_decisions(live, dry)
    assert dry.dry_run and diff.outcome_before == Outcome.ALLOW and diff.outcome_after == Outcome.BLOCK
    assert [(c.entity_type, c.before, c.after) for c in diff.changes] == [("iban", Action.REDACT, Action.BLOCK)]


# --- store, versions, scopes -----------------------------------------------------------

def test_versions_are_immutable(tmp_path):
    store = FilePolicyStore(tmp_path)
    p1 = Policy.from_yaml(SPEC_POLICY)
    store.save(p1)
    with pytest.raises(PolicyError):
        store.save(p1)  # same version again
    with pytest.raises(PolicyError):
        store.save(p1.model_copy(update={"version": 3}))  # gap
    p2 = store.save(p1.model_copy(update={"version": 2, "default_action": Action.REDACT}))
    reloaded = FilePolicyStore(tmp_path)
    assert reloaded.get("legal-default").version == 2
    assert reloaded.get("legal-default", 1).default_action == Action.ALLOW
    assert [h.version for h in reloaded.history("legal-default")] == [1, 2]
    assert reloaded.history("legal-default")[1].hash == p2.content_hash


def test_extends_and_scope_resolution():
    store = InMemoryPolicyStore()
    store.save(builtin_policy())
    store.save(Policy.from_yaml("""
name: firm-a
scope: {tenant: firm-a}
extends: legal-default
rules:
  - {id: firm_a_emails, entity: email, action: redact, priority: 5}
default_action: redact
"""))
    store.save(Policy.from_yaml("""
name: firm-a-criminal
scope: {tenant: firm-a, team: criminal}
extends: firm-a
document_rules:
  - {id: all_critical_block, min_risk: critical, action: block}
default_action: redact
"""))
    assert store.resolve_for().name == "legal-default"
    assert store.resolve_for(tenant="other").name == "legal-default"
    firm = store.resolve_for(tenant="firm-a")
    assert firm.name == "firm-a" and {"parties", "firm_a_emails"} <= {r.id for r in firm.rules}
    team = store.resolve_for(tenant="firm-a", team="criminal")
    assert team.name == "firm-a-criminal" and "firm_a_emails" in {r.id for r in team.rules}
    assert store.resolve_for(tenant="firm-a", team="corporate").name == "firm-a"


def test_extends_rejects_unknown_parent_and_id_clash():
    store = InMemoryPolicyStore()
    with pytest.raises(PolicyError):
        store.save(Policy.from_yaml("name: child\nextends: missing\n"))
    store.save(builtin_policy())
    # Rejected at save time: a stored version is immutable and would stay unusable.
    with pytest.raises(PolicyError):
        store.save(Policy.from_yaml("name: child\nextends: legal-default\nrules:\n  - {id: parties, entity: x, action: allow}\n"))
    assert store.names() == ["legal-default"]


def test_circular_extends_is_rejected_on_save():
    store = InMemoryPolicyStore()
    store.save(Policy.from_yaml("name: a\nrules:\n  - {id: a1, entity: person, action: redact}\n"))
    with pytest.raises(PolicyError):
        store.save(Policy.from_yaml("name: a\nversion: 2\nextends: a\n"))
    store.save(Policy.from_yaml("name: b\nextends: a\n"))
    with pytest.raises(PolicyError):
        store.save(Policy.from_yaml("name: a\nversion: 2\nextends: b\n"))
    assert store.effective("b").rules[0].id == "a1" and store.get("a").version == 1


def test_failed_file_write_leaves_no_phantom_version(tmp_path):
    store = FilePolicyStore(tmp_path)
    store.save(Policy.from_yaml("name: p\n"))
    (tmp_path / "p" / "v2.yaml").write_text("name: p\nversion: 2\n", encoding="utf-8")  # written by another process
    with pytest.raises(PolicyError):
        store.save(Policy.from_yaml("name: p\nversion: 2\n"))
    assert store.get("p").version == 1


def test_malformed_yaml_is_a_policy_error_without_echo():
    with pytest.raises(PolicyError) as exc:
        Policy.from_yaml("name: p\nrules: [secret-marker\n")
    assert "secret-marker" not in str(exc.value)


# --- end-to-end pipeline ---------------------------------------------------------------

def test_pipeline_returns_text_only_when_allowed():
    pipe = Pipeline()
    ok = pipe.protect("Herr Max Mustermann bittet um Rückruf unter max@example.org.")
    assert ok.allowed and "Mustermann" not in ok.text and "max@example.org" not in ok.text
    held = pipe.protect("Herr Max Mustermann leidet an einer Depression.")
    assert not held.allowed and held.text is None and held.anonymization is None
    assert held.decision.outcome == Outcome.LOCAL_ONLY
    local = pipe.protect("Herr Max Mustermann leidet an einer Depression.", destination="local")
    assert local.allowed
