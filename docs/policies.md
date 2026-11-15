# Policy Engine

`packages/core/src/cato/policy/` decides per entity and per document what happens before data leaves. Evaluation is **deterministic**: no LLM and no randomness decide whether critical information is passed on.

## Format

```yaml
name: legal-default          # lowercase, a-z0-9_.-
version: 1                   # immutable; changes = new version
extends: null                # optional parent policy
scope: {tenant: null, team: null}

rules:
  - id: parties              # optional, otherwise rule_1, rule_2, ...
    entity: [person, organization]
    action: pseudonymize
  - id: special_categories_external
    category: special_category
    destinations: [external]
    action: local_only
    priority: 10

document_rules:
  - id: criminal_privileged_review
    min_risk: critical
    signals: [criminal_proceeding]
    destinations: [external]
    action: review

default_action: redact
critical_floor: true
critical_floor_action: pseudonymize
review_uncertain: true
```

Unknown fields, actions or destinations are rejected (`cato policy-validate file.yaml`).

### Rule conditions

All conditions must hold. Lists inside a condition mean "one of".

| Condition | Meaning |
|---|---|
| `entity` | Entity type (`person`, `iban`, custom types, ...) |
| `category` | `personal_data`, `financial_data`, `legal_data`, `special_category`, ... |
| `risk`, `min_risk` | Risk from classification |
| `role` | Procedural role (`client`, `accused`, `witness`, ...) |
| `signals` | Context signal near the entity |
| `document_signals` | Context signal anywhere in the document |
| `max_confidence` | Only uncertain detections |
| `destinations` | `external` (cloud LLM) or `local` (local model) |

### Actions

| Action | Effect |
|---|---|
| `allow` | Unchanged |
| `replace`, `pseudonymize`, `tokenize`, `generalize`, `mask`, `redact` | Anonymization method (see anonymization.md) |
| `review` | Document waits for human approval |
| `local_only` | Only a local model may process it |
| `block` | Must not be sent |

## Evaluation

1. **Per entity:** collect all matching rules, then pick the winner in this order:
   1. Highest `priority`.
   2. On a tie, the **more restrictive action** (`block > local_only > review > redact > tokenize > pseudonymize > mask > generalize > replace > allow`).
   3. Then the rule order.

   Overruled rules are recorded in the decision.
2. **No match:** `default_action` applies.
3. **Critical floor:** an entity classified `critical` never goes to `external` unchanged. `allow` becomes `critical_floor_action`, unless the rule sets `allow_critical: true` explicitly.
4. **`local_only` on a `local` destination** counts as `allow`.
5. **Document outcome** is the most restrictive of:
   - the gate actions of the entities,
   - matching document rules,
   - `review_uncertain` (uncertain detections from classification).

   Order: `block > local_only > review > allow`.

`PolicyDecision.plan` returns the method per detection for the anonymizer. `may_send` says whether text may be produced at all.

## Pipeline

```python
from cato.pipeline import Pipeline

result = Pipeline().protect(text, destination="external", namespace="matter-17")
if result.allowed:
    send_to_llm(result.text)
else:
    hold(result.decision.outcome, result.decision.reasons)
```

When the outcome is not "allow", `text` is `None`. No anonymized text is produced at all in that case, so nothing can be forwarded by accident.

```bash
cato protect brief.txt --destination external          # exit code 2 if not allowed
cato protect brief.txt --policy firm.yaml --dry-run
```

## Versioning, audit, dry run

- **Immutable versions:** `InMemoryPolicyStore` / `FilePolicyStore` (`<dir>/<name>/v<N>.yaml`, write-once) only accept `version = latest + 1`.
- **Audit:** each decision carries `policy` (`name@vN`) and `policy_hash` (SHA-256 of the canonical content). This lets you prove later which rules applied.
- **Dry run:** evaluate a candidate policy with `dry_run=True`. `diff_decisions(live, candidate)` shows which entities and which outcome would change.

## Clients and teams

`scope` and `extends`:
- `resolve_for(tenant, team)` picks the most specific policy: team, then tenant, then global.
- `extends` adds the parent's rules (parent rules first). Reusing a rule ID (including auto-generated ones such as `rule_1`) or a circular chain is rejected when the policy is saved.

## Built-in policy `legal-default`

`cato.policy.builtin_policy()` is a conservative starting point:
- Pseudonymize parties and contact data.
- Redact identifiers.
- Generalize the date of birth.
- Special categories: `local_only` for external destinations.
- Critical documents in criminal matters: `review` for external destinations.
- `default_action: redact`.

Copy it, adapt it and version it as your own policy.

## Not yet included

- **Management API and roles (RBAC):** step 5 (REST API) or Phase 4.
- **Graphical editor:** dashboard, Phase 3.
- **A real approval workflow for `review`:** the review queue needs persistence. The engine only delivers the decision.
