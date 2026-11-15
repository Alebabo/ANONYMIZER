# Prompts: versions, labels, drafts from agents

Cato keeps prompt versions and labels, lets agents propose new versions, and leaves the decision about what runs in production with a person. Every write is checked for customer data first.

| `CATO_PROMPTS` | Storage | Note |
|---|---|---|
| `local` | SQLite (`CATO_PROMPTS_DB`, default `data/prompts.db`) | Versions append-only, labels per organization |
| `langfuse` | Langfuse prompt management (`/api/public/v2/prompts`) | Uses `CATO_PROMPTS_URL`/`_PUBLIC_KEY`/`_SECRET_KEY`, or the `CATO_SOURCE_*` settings when the source is Langfuse. Default organization only |

If your application already loads prompts from Langfuse, use the `langfuse` backend: Cato adds the checks and the audit trail, Langfuse stays the single source of truth.

## Workflow

1. **Analyse:** the agent reads conversations (`conversation_stats(group_by="prompt_version")`, `get_conversation`) and the current prompt (`get_prompt(name, label="production")`).
2. **Draft:** `create_prompt_draft(name, text, note)` saves a new version **without labels**.
3. **Review:** a person opens *Prompts → name* in the dashboard, reads the diff against the previous version and any warnings.
4. **Promote:** an admin sets `production` (or `staging`) on that version. Recorded in the audit log with the previous version.
5. **Measure:** once the application serves the new version and reports it (trace metadata or the `prompt_version` field of the source), `conversation_stats(group_by="prompt_version")` compares old and new.

Agents cannot do step 4: there is no MCP tool for labels, and the REST endpoint needs an admin key or an admin session.

## Checks on every new version

| Check | Result |
|---|---|
| Deterministic detections (e-mail, phone, IBAN, address, honorific + name, "mein Name ist …", custom patterns) | **Rejected** (422) with the entity types, never the values |
| A full name (first and last) found by NER | **Rejected** |
| A single word found only by NER ("Lisa", or German imperatives such as "Nenne") | **Saved with a warning**; the warning (types only) is in the response and the audit entry |
| Cato placeholders (`PERSON_001`, `[REDACTED]`) | **Rejected**: pasting protected output into a prompt would overwrite real template text with pseudonyms |
| Note and config | Same deterministic check |
| Allowed | Organizations, places, dates, amounts, public references; template variables such as `{{customer_name}}` |

Context words such as "example" lower the risk of a name elsewhere in Cato. For prompts they do not count: a real customer labelled as an example is still a real customer.

## Reading

Prompts are returned as stored. If a stored version contains sensitive data (for example one created directly in Langfuse), readers receive it anonymized with `protected: true` and a notice. Fix it at the source; drafts built from the anonymized text are rejected because of the placeholders.

## API

| Method | Path | Key | Function |
|---|---|---|---|
| GET | `/v1/prompts` | API | Names, latest version, labels |
| GET | `/v1/prompts/{name}?version=&label=` | API | One version (`label=latest` by default) |
| GET | `/v1/prompts/{name}/history` | API | Versions with labels, note, author, hash |
| GET | `/v1/prompts/{name}/diff?from_version=&to_version=` | API | Unified diff, `config_changed` |
| POST | `/v1/prompts` | API | `{"name", "prompt": "text" \| [{"role","content"}], "config"?, "note"?}` → new version without labels |
| POST | `/v1/prompts/{name}/labels` | Admin | `{"version", "label"}`; returns the previous version |

Names: letters, digits, `_ . -` (max. 128). Labels: lowercase, digits, `_ -` (max. 32); `latest` is reserved and always points to the newest version.

Python SDK: `cato.prompts()`, `cato.prompt(name, label="production")`, `cato.create_prompt(name, text, note=...)`, `cato.set_prompt_label(name, version)` (admin).
