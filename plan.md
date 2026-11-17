# Plan: Anonymizer as a privacy proxy between Claude and production chat data

Status: packages 1–7 implemented, package 8 partly (see section 11). Scope: read customer chat history and manage prompts through Claude without any raw customer data leaving the company network.

## 1. Problem

- Claude (Code/Desktop) may only connect to `sbx`/`develop`, never to `prod`, because prod holds customer data.
- The work that needs prod is: reading real conversations, judging prompt quality, editing prompts and tracking which prompt version produced which outcome.
- Today this means copy-paste or working on synthetic data. Both are slow and the second is misleading.

## 2. Target

Anonymizer runs **inside the company network next to prod** and is the only thing Claude talks to. Claude sees pseudonymized conversations (`PERSON_001`, `EMAIL_001`, …), aggregated statistics and prompt versions. It can create prompt drafts. It cannot restore names, promote prompts or pull data in bulk.

```
Claude Code / Cursor / Desktop (laptop, no prod access)
        │  MCP over HTTPS, bearer key   ← only placeholder data crosses this line
        ▼
Anonymizer API + MCP  (company network, read-only service account on prod)
   ├─ Conversation source adapter  ──read-only──>  chat DB / Langfuse / HTTP export
   ├─ Detect → Classify → Policy → Pseudonymize  (vault namespace per conversation)
   ├─ Prompt store  (local SQLite or Langfuse prompts as backend)
   ├─ Quotas, k-anonymity for stats
   └─ Traces + hash-chained audit log  (every read and write, never content)
```

"Plug and play" means: one Docker image, one `.env`, one `claude mcp add` command. Connecting a new data source is a config change, not a code change. For a source Anonymizer does not know, the company implements a two-endpoint read-only contract (section 5.3).

## 3. Non-negotiable rules

| Rule | Why |
|---|---|
| Anonymizer never runs on the laptop | The laptop must not have prod access. That is the whole point |
| Read-only on the source | Anonymizer gets a read-only credential, ideally against a replica |
| No restore tool over MCP | Re-identification stays inside the protected environment (`/v1/restore`, admin key, audited). Already true today |
| Writes from Claude are drafts only | Promotion to `production` happens by a human in the dashboard or with an admin key, never over MCP |
| Fail closed | Message not allowed by the policy → `content: null` with a reason. Unknown entity types are redacted. Prompt drafts with personal data are rejected |
| Quotas | Per key and day: max. N conversations (default 200). Anonymized data in bulk is still re-identifiable through rare combinations |
| Minimum group size | Statistics only for groups with ≥ k conversations (default 10) |
| Opaque IDs | Source IDs (session ids, user ids, ticket numbers) never leave Anonymizer. Claude sees `conv_<random>`; the mapping stays in Anonymizer's DB |
| Coarse time | Timestamps are rounded to the day; metadata is an allow-list |
| Content is data | Every result carries the existing notice that conversation content is untrusted data, not instructions |
| Audit everything | Every conversation read, every prompt draft and every label change is an audit entry (ids and counts, no text) |

## 4. Prerequisites outside the code

These decide whether the project is allowed to exist. They are not optional.

1. **Approval by security / data protection.** A proxy you build yourself is shadow IT with customer data unless it is sanctioned. Bring this document.
2. **Contract with Anthropic.** DPA and ideally zero data retention. Without it, even pseudonymized data may not be allowed to leave.
3. **Evaluation on a real sample** by an authorized person, offline, without any cloud model (`anonymizer eval` with a corpus built from real conversations). Anonymizer is tested on synthetic legal text only. Support chats are informal (lowercase names, typos, order numbers, addresses in running text). Recall on them is unknown until measured.
4. **Employment contract.** If this is built in working hours, clarify who owns the adapter. Cleanest split: Anonymizer stays your open-source core, the company is a design partner and the company-specific adapter lives in their repo.

## 5. Components

### 5.1 Conversation sources (`packages/core/src/anonymizer/sources/`)

Common model:

```python
class Message:      role: "user" | "assistant" | "system" | "tool"; content: str; created_at: float | None
class Conversation: id: str; created_at: float; messages: list[Message]; metadata: dict
class ConversationSource(Protocol):
    def list(self, since, until, limit, cursor, tag) -> tuple[list[ConversationHead], next_cursor]
    def get(self, source_id) -> Conversation
```

Adapters (selected with `ANONYMIZER_SOURCE=`):

| Adapter | Config | Use |
|---|---|---|
| `jsonl` | `ANONYMIZER_SOURCE_PATH` | Exports, local testing, demo. One conversation per line in the model above |
| `http` | `ANONYMIZER_SOURCE_URL`, `ANONYMIZER_SOURCE_KEY` | Generic contract (5.3). The company exposes two read-only endpoints on prod |
| `langfuse` | `ANONYMIZER_SOURCE_URL`, `ANONYMIZER_SOURCE_PUBLIC_KEY`, `ANONYMIZER_SOURCE_SECRET_KEY` | Sessions → conversations, traces → messages (input/output). Read via the Langfuse public API |

A `sql` adapter (read-only SQLAlchemy query) is deliberately not in v1: every company schema differs, and the `http` contract is the smaller surface.

### 5.2 Conversation service (`anonymizer/conversations.py`)

- `ConversationStore` (SQLite, `ANONYMIZER_CONVERSATIONS_DB`): opaque id ↔ source id, per-key daily counters, nothing else.
- `list`: heads only (opaque id, day, message count, language, allow-listed tags). Tags are scanned; a tag with a detection is dropped.
- `get`: every message through the existing `Pipeline.protect` with destination `external` and one vault namespace per conversation, so `PERSON_001` is the same person across all messages. Most restrictive outcome wins. Messages the policy refuses come back as `content: null, withheld: true, reason`.
- `stats`: counts grouped by `day | tag | prompt | prompt_version`; groups below `ANONYMIZER_CONVERSATIONS_MIN_GROUP` are suppressed.
- Quota: `ANONYMIZER_CONVERSATIONS_DAILY_LIMIT` per principal. Exceeded → 429 / tool error.
- Every `get` writes a trace (`/v1/conversations/{id}`, metadata only, same store as the gateway) and an audit entry.
- Search is **not** in v1. A search over raw data turns the API into an oracle ("are there chats mentioning Müller?"). A search over an anonymized index needs a full pre-processing pass; that is Phase 3.

### 5.3 HTTP source contract (what a company implements)

Read-only, bearer-authenticated, JSON:

```
GET {base}/conversations?since=<unix>&until=<unix>&limit=<n>&cursor=<opaque>&tag=<t>
  → {"data": [{"id": "...", "created_at": 1731600000, "message_count": 7,
               "language": "de", "tags": ["billing"], "prompt": "support@v12"}], "next_cursor": "..."}
GET {base}/conversations/{id}
  → {"id": "...", "created_at": ..., "metadata": {...},
     "messages": [{"role": "user", "content": "...", "created_at": ...}, ...]}
```

Documented in `docs/conversations.md` with a 30-line FastAPI/Express example. This is the plug-and-play path for any internal chat DB.

### 5.4 Prompt store (`anonymizer/prompts.py`)

Interface (same for both backends, `ANONYMIZER_PROMPTS=local|langfuse`):

```
list(org)                              → names with latest version and labels
get(org, name, version | label)        → text, config, version, labels, hash
history(org, name)                     → versions with note, author, created_at
create_version(org, name, text, config, note, actor)   → draft (no label)
set_label(org, name, version, label, actor)            → production | staging | custom
diff(org, name, from, to)              → unified diff
```

- `local`: SQLite (`ANONYMIZER_PROMPTS_DB`), versions append-only, labels as a separate table.
- `langfuse`: thin proxy to `/api/public/v2/prompts`. Anonymizer adds the scan, the audit entry and the rule that MCP can only create unlabeled versions. If the company already manages prompts in Langfuse, this is the smallest useful cut: no second source of truth.
- **Scan before save:** the prompt text goes through the detector. Any `sensitive`/`critical` entity → 422. This keeps customer examples out of prompts.
- Prompt metrics come from `conversation_stats(group_by=prompt_version)`, which only works if the source exposes which prompt version served a conversation (Langfuse does via trace metadata; the HTTP contract has the optional `prompt` field).

### 5.5 REST endpoints (`anonymizer/api/app.py`)

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /v1/conversations` | key | heads, paginated |
| `GET /v1/conversations/stats` | key | k-anonymous aggregates |
| `GET /v1/conversations/{id}` | key | protected messages, quota, trace, audit |
| `GET /v1/prompts`, `GET /v1/prompts/{name}`, `GET /v1/prompts/{name}/history`, `GET /v1/prompts/{name}/diff` | key | |
| `POST /v1/prompts` | key | creates a draft version, scanned |
| `POST /v1/prompts/{name}/labels` | **admin** (session or admin key) | promotion; audited with before/after |
| `GET /v1/sources` | key | adapter type and host, never credentials |

### 5.6 MCP (`anonymizer/mcp/`)

New tools, shared by stdio and HTTP (`AnonymizerTools` gets optional `ConversationService` and `PromptStore`):

| Tool | Annotation |
|---|---|
| `list_conversations(since?, until?, tag?, limit?, cursor?)` | read-only |
| `get_conversation(id)` | read-only, quota |
| `conversation_stats(since?, until?, group_by)` | read-only |
| `list_prompts()`, `get_prompt(name, version? \| label?)`, `diff_prompt(name, from, to)` | read-only |
| `create_prompt_draft(name, text, note)` | **write**, not idempotent, so clients ask for confirmation |

Not provided over MCP on purpose: `set_label`, `restore`, anything taking a `destination`, `policy` or `namespace` argument (existing rule).

Transport:

- **stdio** stays for local use (`anonymizer-mcp`), now with the same tools when `ANONYMIZER_SOURCE` / `ANONYMIZER_PROMPTS` are set.
- **Streamable HTTP** mounted at `/mcp` on the existing API (`ANONYMIZER_MCP_HTTP=1`). Auth: `Authorization: Bearer <anonymizer key>` resolved with the existing `resolve()` (env key, dashboard-created key or session). The principal gives org scope, quota bucket and audit actor. Client setup:

  ```bash
  claude mcp add --transport http anonymizer https://anonymizer.internal/mcp --header "Authorization: Bearer anonymizer_..."
  ```

  Claude Desktop / claude.ai custom connectors need OAuth; that is Phase 3 (the `mcp` SDK already ships the server side). Claude Code and Cursor work with the header.
- TLS terminates at the reverse proxy as today; DNS-rebinding protection stays on.

### 5.7 Dashboard (Next.js)

- **Prompts** page: list, version history, diff, labels, a **Promote** form (live mode, admin). This is the human step the design relies on, so it must exist in the UI.
- **Conversations** page: heads list, protected view of one conversation, quota display. Read-only.
- Both get demo data in `lib/mock.ts` like the other pages.

### 5.8 Detection for support chats

The current recognizers target legal text. Needed additions, all deterministic:

- Customer number, order number, ticket id (configurable regex per deployment: `ANONYMIZER_CUSTOM_PATTERNS=/path/to/patterns.yaml`).
- Street addresses in running text (DE/EN).
- Lowercase and typo-tolerant name detection via NER confidence thresholds (already there, needs tuning on the sample from 4.3).
- A `support-default` policy next to `legal-default`: coarsen dates and places, `health_data`/`financial` → `critical`, unknown types → redact.

## 6. Configuration (`.env` additions)

```
# Conversation source
ANONYMIZER_SOURCE=jsonl|http|langfuse
ANONYMIZER_SOURCE_PATH=            # jsonl
ANONYMIZER_SOURCE_URL=             # http / langfuse
ANONYMIZER_SOURCE_KEY=             # http
ANONYMIZER_SOURCE_PUBLIC_KEY=      # langfuse
ANONYMIZER_SOURCE_SECRET_KEY=      # langfuse
ANONYMIZER_CONVERSATIONS_DB=/data/conversations.db
ANONYMIZER_CONVERSATIONS_DAILY_LIMIT=200
ANONYMIZER_CONVERSATIONS_MIN_GROUP=10
ANONYMIZER_CONVERSATIONS_POLICY=support-default

# Prompts
ANONYMIZER_PROMPTS=local|langfuse
ANONYMIZER_PROMPTS_DB=/data/prompts.db

# MCP over HTTP
ANONYMIZER_MCP_HTTP=1
```

Vault key (`ANONYMIZER_VAULT_KEY`) becomes required for conversations: without it, placeholders cannot be stable per conversation.

## 7. Work packages

| # | Package | Content | Effort |
|---|---|---|---|
| 1 | Sources | models, `jsonl`, `http`, `langfuse` adapters, tests with mocked `httpx` transport | 1 day |
| 2 | Conversation service | store, opaque ids, protection with per-conversation namespace, withheld messages, quota, stats with k-anonymity, trace + audit | 1.5 days |
| 3 | Prompt store | local backend, Langfuse backend, scan-before-save, diff, labels, audit | 1 day |
| 4 | REST | endpoints from 5.5, schemas, no-leak tests | 0.5 day |
| 5 | MCP | tools in `AnonymizerTools`, HTTP mount with bearer auth, principal in tool context, tests for both transports | 1 day |
| 6 | Dashboard | Prompts page with promote, Conversations page, mock data | 1 day |
| 7 | Docs & packaging | `docs/conversations.md`, `docs/prompts.md`, `docs/mcp.md` update, README, `.env.example`, SDK methods | 0.5 day |
| 8 | Detection for chats | custom patterns, address recognizer, `support-default` policy, corpus `tests/corpus/de_support.yaml` | 1–2 days, after the real-sample evaluation |

Order: 1 → 2 → 3 → 4 → 5 → 7 (usable end to end over MCP), then 6, then 8 once there is a measured sample. Packages 1–5 and 7 are one branch and one PR; 6 and 8 are separate PRs.

## 8. Tests that must exist

- **No leak:** for every endpoint and tool, a dump of the response never contains any of the secret strings from the fixture (same pattern as `test_mcp.py`/`test_api.py`).
- **Opaque ids:** source ids never appear in responses, traces or audit entries.
- **Fail closed:** a message the policy refuses → `content: null`; a prompt with an IBAN → 422; unknown adapter → startup error.
- **Quota:** request N+1 on the same day → 429; another key is unaffected; the counter is per organization and key.
- **k-anonymity:** a group with k−1 conversations is absent from stats.
- **Consistency:** the same person in message 1 and message 5 gets the same placeholder; a different conversation gets a fresh numbering.
- **Promotion:** `set_label` with a user key → 403; over MCP the tool does not exist.
- **MCP HTTP auth:** no header → 401; wrong key → 401; valid key → tool list, principal org used for scoping.
- **Audit:** every `get_conversation`, draft and label change produces one entry and the chain verifies.

## 9. Rollout

1. **Approval** (section 4). Nothing else starts before this.
2. **PoC on sbx/dev** with the `jsonl` or `http` adapter against sandbox data. Measures nothing about recall, proves the workflow.
3. **Offline evaluation** on a prod sample by an authorized person: `anonymizer eval` on a corpus built from real conversations, tune recognizers, add the custom patterns (package 8).
4. **Prod read-only** with the limits from section 3, one API key per person, audit review weekly for the first month.
5. **Prompt workflow**: Claude drafts, human promotes in the dashboard, `conversation_stats(group_by=prompt_version)` closes the loop.

## 10. Open decisions

| Question | Default if unanswered |
|---|---|
| Where does the chat history live: own DB, a support tool, or Langfuse traces? | Build all three adapters; `http` is the fallback for anything else |
| Are prompts already in Langfuse? | Support both backends; recommend `langfuse` if yes, to avoid a second source of truth |
| Does Anonymizer run as Docker Compose or Kubernetes in the company? | Compose first (exists); Helm is on the roadmap anyway |
| Which fields count as tags/metadata and are safe to expose? | Allow-list `tags`, `language`, `channel`, `prompt`, `prompt_version`; everything else dropped |
| Is k=10 and 200 conversations/day acceptable for the job? | Start strict; raise with the data-protection contact, not unilaterally |

## 11. Implementation status

| # | Package | Status | Where |
|---|---|---|---|
| 1 | Sources | done: `jsonl`, `http`, `langfuse` | `packages/core/src/anonymizer/sources/` |
| 2 | Conversation service | done | `packages/core/src/anonymizer/conversations.py` |
| 3 | Prompt store | done: `local`, `langfuse` | `packages/core/src/anonymizer/prompts.py` |
| 4 | REST | done | `packages/core/src/anonymizer/api/app.py` |
| 5 | MCP | done: 8 new tools, stdio + HTTP at `/mcp` | `packages/core/src/anonymizer/mcp/server.py` |
| 6 | Dashboard | done: Conversations, conversation detail, Prompts, prompt detail with promote form | `app/(app)/conversations`, `app/(app)/prompts` |
| 7 | Docs & packaging | done: `docs/conversations.md`, `docs/prompts.md`, `docs/mcp.md`, `.env.example`, Dockerfile, SDK, `anonymizer source-check` | |
| 8 | Detection for chats | partly: `support-default` policy, `ANONYMIZER_CUSTOM_PATTERNS`, self-introduction recognizer, synthetic corpus `de_support`. **Open: evaluation on a real sample (section 4.3)** | `packages/core/src/anonymizer/detect/` |

Deviations from the plan, with reasons:

- **Vault optional, not required.** Without `ANONYMIZER_VAULT_KEY` each read uses a fresh in-memory vault: placeholders are consistent within one read, not across reads, and cannot be restored. Fewer mandatory settings for a first start; production should set the key.
- **Prompt write check split into hard and soft.** German NER marks imperatives ("Nenne", "Kurz") and persona names ("Lisa") as persons. Rejecting on every NER hit made German prompts unsavable. Now: deterministic hits and full names (two or more tokens) reject; single-word NER hits are saved with a warning (types only) in the response and the audit entry, for the human who promotes.
- **Prompt names without `/`.** Langfuse folders are not supported; keeps routing unambiguous.
- **Labels on tags/prompt names:** dropped on any deterministic hit or NER confidence ≥ 0.6 (single words such as "retoure" scored 0.45 as a location).
- **Statistics by prompt version with Langfuse:** session listings carry no prompt, so this grouping needs the `http`/`jsonl` source (documented).

Found while testing on the synthetic chats:

- "Mein Name ist Hans Beispiel." was **not detected** by rules or NER and would have leaked. Fixed with the self-introduction recognizer (`person_self_intro`), covered by the `de_support` corpus.
- NER over-redacts lowercase chat text ("ich komme nicht mehr in mein konto" → two `PERSON_` placeholders). Readability cost, no leak; left as is and documented.

## 12. Review after implementation

End-to-end checks (real server, official MCP client over HTTP and stdio, dashboard in live mode with login):

- All 24 synthetic conversations read over MCP HTTP and in the dashboard: no name, e-mail, customer/ticket number, IBAN, phone, diagnosis or source id in any response. Server log: no customer data.
- Wrong or missing key on `/mcp`: 401. Dashboard link prefetching does not consume quota. Promote form works and is audited.

Findings and fixes:

| Finding | Fix |
|---|---|
| `tag` filter was an oracle: "tag = Max Mustermann" returned 1 vs. 0 conversations | Filters with detectable data are rejected before the source is asked |
| Quota check and increment were separate: parallel reads could exceed the limit; failed reads counted | Atomic reservation in SQLite, released when the read fails |
| Prompt notes and config (e.g. Langfuse commit messages) were returned unchecked | Same read protection as the prompt text |
| Unexpected exceptions in MCP tools reached the model with their message (could contain source data) | Generic tool error; details only in the server log |
| Unknown `ANONYMIZER_CONVERSATIONS_POLICY` failed on the first request | Checked at startup |

Known limits that remain (documented): recall on real chats unmeasured; NER over-redaction on lowercase text; k-anonymity protects aggregates only, since the listing shows per-conversation metadata; no OAuth for remote MCP.
