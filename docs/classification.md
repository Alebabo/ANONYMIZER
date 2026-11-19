# Classification Engine

`packages/core/src/anonymizer/classify/` assigns a risk level to each detection and to the whole document, with a reason for every step. It's deterministic: the same input and configuration always give the same output. No LLM is involved.

## Risk levels

| Level | Value | Meaning |
|---|---|---|
| 1 | `low` | Public or uncritical information |
| 2 | `sensitive` | Personal or confidential data; the policy decides |
| 3 | `critical` | Client secrets, special categories, identifiers; must not be passed on unprotected |

## Rules per entity (in this order)

1. **Base risk** of the entity type (`base_risk`). Unknown or custom types default to `sensitive`.
2. **Role** (`role_risk`): client, accused and injured party raise to `critical`; plaintiff, defendant and witness at least to `sensitive`. Can only raise.
3. **Context signals** (`signal_rules`): e.g. person, address or case number near `client_relationship` or `criminal_proceeding` raise to `critical`. Can only raise.
4. **Link rules** (`link_rules`): a person within 200 characters of special-category data (health, criminal record, religion, ...) in the same paragraph is the data subject and becomes `critical`. Can only raise.
5. **Example context**: lowers one level, but only under these conditions:
   - the signal is near the entity (not document-wide);
   - the type is lowerable (persons, contact data, amounts, ...);
   - no validated identifier;
   - no conflicting signal (`client_relationship`, `criminal_proceeding`, `confidential`).
6. **Overrides** (`overrides`): fixed level by type, category or recognizer, e.g. from a team policy.
7. **Manual correction**: `classify(..., corrections={detection_id: level})`, recorded as reason `manual`.
8. **Review flag**: confidence below `review_threshold` (0.6) at risk ≥ `sensitive`, or a failed checksum. The flag never lowers a level.

## Document

- The level is the highest entity level. `confidence` is the highest confidence among the detections that set the level.
- `needs_review` is set if one entity needs review **or** the detection ran in degraded mode (e.g. NER models missing). In degraded mode, an empty or `low` document is raised to `sensitive`, because a missing hit there is not evidence.
- `counts` gives the number of entities per level.

## Example from the spec

| Text | Person | Reasons |
|---|---|---|
| "Beispiel: Herr Max Mustermann ist ein fiktiver Name ..." | low | `base:person`, `example:lowered` |
| "Herr Max Mustermann ist unser Mandant im laufenden Strafverfahren." | critical | `base:person`, `signal:client_context` |
| "Beispiel: Herr Max Mustermann ist unser Mandant im Strafverfahren." | critical | `example:blocked` (conflict, decided conservatively) |

## Configuration (YAML)

```yaml
review_threshold: 0.7
base_risk:
  organization: sensitive        # merged with the defaults
role_risk:
  witness: critical
overrides:
  - entity_type: email
    risk: critical
    reason: "Team policy: no contact data"
```

```bash
anonymizer classify brief.txt --config classifier.yaml
```

## Output

`EntityClassification` and `DocumentClassification` contain offsets, types, levels, reasons and the attributes `role`, `ref` and `subtype`, but **no raw values**. You can log them and show them in traces.

## Known simplifications

- **Case numbers** are `sensitive` by default, even in published judgments. This is conservative, because there is no reliable way to tell "public" from "our own file".
- **Example context** only acts locally. A heading "Beispiel" in a separate paragraph doesn't lower the persons below it, on purpose: a stray "z. B." must not lower a whole real document.
- **Document level = maximum.** Aggregating many `sensitive` entities into `critical` (re-identifiability through combination) is not modelled yet.
