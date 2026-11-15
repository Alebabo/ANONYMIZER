# Conversations: protected access to customer chats

Cato can sit between an AI agent (Claude Code, Cursor, any MCP or REST client) and the place where customer chats are stored. The agent reads conversations through Cato and only ever receives protected messages: `PERSON_001` instead of names, `EMAIL_001` instead of addresses, `[REDACTED]` instead of IBANs, and `content: null` for messages the policy keeps away from external models.

Typical use: your team may connect AI tools to sandbox and development, but not to production, because production holds customer data. Cato runs **inside your network next to production**, reads with a read-only account and hands out only what the policy allows.

```
Claude Code / Cursor (laptop, no production access)
        │  MCP over HTTPS + Cato key   ← only placeholder data crosses this line
        ▼
Cato (your network)  ──read-only──>  chat database / Langfuse / export
```

> **Before you connect production:** get approval from your security / data-protection contact and check the contract with your model provider. Cato is a technical safeguard, not a legal basis. Measure recall on a sample of your own conversations first (see [Evaluation](#evaluation-before-production)).

## Quickstart with the synthetic example

```bash
cd packages/core && pip install -e . && cd ../..
CATO_API_KEYS=cato_demo_key_change_me_0123456789 \
CATO_SOURCE=jsonl CATO_SOURCE_PATH=examples/support/conversations.jsonl \
CATO_CUSTOM_PATTERNS=examples/support/patterns.yaml \
CATO_PROMPTS=local CATO_MCP_HTTP=1 cato-api
```

```bash
claude mcp add --transport http cato http://127.0.0.1:8080/mcp \
  --header "Authorization: Bearer cato_demo_key_change_me_0123456789"
```

Then ask Claude: *"Which topics come up most in the support chats, and how does support-bot@12 compare to @11?"*

Check the connection without printing any content:

```bash
CATO_SOURCE=... cato source-check --protect
```

## Sources

| `CATO_SOURCE` | Settings | Use |
|---|---|---|
| `jsonl` | `CATO_SOURCE_PATH` | Exports, tests, demos. One conversation per line (format below). Re-read on every call |
| `http` | `CATO_SOURCE_URL`, `CATO_SOURCE_KEY` | Any chat database: you implement two read-only endpoints (contract below) |
| `langfuse` | `CATO_SOURCE_URL`, `CATO_SOURCE_PUBLIC_KEY`, `CATO_SOURCE_SECRET_KEY` | Langfuse sessions as conversations, traces as turns |

`CATO_SOURCE_TIMEOUT` (seconds, default 30) applies to `http` and `langfuse`.

### Conversation format (jsonl and http)

```json
{"id": "sess-0001", "created_at": 1762905600, "language": "de", "channel": "web",
 "tags": ["billing"], "prompt": "support-bot", "prompt_version": 12,
 "messages": [{"role": "user", "content": "...", "created_at": 1762905600},
              {"role": "assistant", "content": "...", "created_at": 1762905690}]}
```

`role` is `user`, `assistant`, `system` or `tool`. Everything except `id`, `created_at` and `messages` is optional.

### HTTP contract

Two read-only endpoints, bearer-authenticated, JSON. Implement them next to your chat database; Cato needs nothing else.

```
GET {CATO_SOURCE_URL}/conversations?since=<unix>&until=<unix>&limit=<n>&cursor=<opaque>&tag=<t>
  → {"data": [ {conversation without "messages", optional "message_count"} ], "next_cursor": "..." | null}

GET {CATO_SOURCE_URL}/conversations/{id}
  → {conversation with "messages"}          404 if unknown
```

Newest first. `cursor` is whatever you returned as `next_cursor`; Cato never shows it to clients.

Minimal implementation (FastAPI, read-only database user):

```python
from fastapi import FastAPI, Header, HTTPException

app = FastAPI()
KEY = "..."  # the value of CATO_SOURCE_KEY

def auth(authorization: str):
    if authorization != f"Bearer {KEY}":
        raise HTTPException(401)

@app.get("/conversations")
def conversations(limit: int = 50, cursor: str | None = None, since: float | None = None,
                  until: float | None = None, tag: str | None = None, authorization: str = Header("")):
    auth(authorization)
    rows = db.fetch_sessions(limit=limit, before_id=cursor, since=since, until=until, tag=tag)
    return {"data": [{"id": r.id, "created_at": r.created_at.timestamp(), "message_count": r.n,
                      "tags": r.tags, "prompt": r.prompt_name, "prompt_version": r.prompt_version}
                     for r in rows],
            "next_cursor": rows[-1].id if len(rows) == limit else None}

@app.get("/conversations/{cid}")
def conversation(cid: str, authorization: str = Header("")):
    auth(authorization)
    s = db.fetch_session(cid)
    if s is None:
        raise HTTPException(404)
    return {"id": s.id, "created_at": s.created_at.timestamp(),
            "messages": [{"role": m.role, "content": m.text, "created_at": m.ts.timestamp()} for m in s.messages]}
```

### Langfuse

- `GET /api/public/sessions` (list) and `GET /api/public/sessions/{id}` (detail) with basic auth.
- Each trace becomes a user turn (`input`) and an assistant turn (`output`). When an application logs the full chat history in every trace input, Cato takes the last user message.
- The prompt that served a trace is read from trace metadata `prompt_name` (or `prompt`) and `prompt_version`. Set them in your application if you want statistics by prompt version.
- Session listings carry no prompt information, so `conversation_stats(group_by="prompt_version")` needs the `http` or `jsonl` source, or a source that includes the prompt in the listing.

## What callers receive

| Endpoint | MCP tool | Content |
|---|---|---|
| `GET /v1/conversations` | `list_conversations` | Opaque id (`conv_…`), day, message count, language, channel, tags, prompt, prompt version |
| `GET /v1/conversations/{id}` | `get_conversation` | Protected messages, outcome, risk, withheld count, trace id, quota |
| `GET /v1/conversations/stats?group_by=` | `conversation_stats` | Counts per group; groups below k suppressed |
| `GET /v1/conversations/quota` | – | Reads used today |
| `GET /v1/sources` | – | Source type and host, prompt backend; never credentials |

## Guarantees

| Rule | How |
|---|---|
| Every message is protected | Each message runs through detection, classification and the conversation policy (`CATO_CONVERSATIONS_POLICY`, default `support-default`) for the `external` destination |
| Same person, same placeholder | One vault namespace per conversation. With `CATO_VAULT_KEY` the placeholders are stable across reads and an admin can restore them (`POST /v1/restore`, namespace `conversation:<id>`); without it they are generated per read |
| Withheld instead of leaked | A message the policy does not allow (e.g. health data under `support-default`) comes back as `content: null` with the reason. Messages over 50,000 characters are withheld unchecked |
| Opaque ids | Source ids and source cursors stay in Cato's database (`CATO_CONVERSATIONS_DB`); callers see `conv_…`/`cur_…`. Ids and cursors are scoped to the organization |
| Metadata allow-list | Day instead of timestamp, minute offsets instead of message times. Tags, channel and prompt names are dropped if they contain anything detectable |
| Quota | `CATO_CONVERSATIONS_DAILY_LIMIT` full reads per key (or dashboard user) and UTC day, default 200. Listing and statistics do not count |
| k-anonymity | Statistics groups with fewer than `CATO_CONVERSATIONS_MIN_GROUP` conversations (default 10) are suppressed; so is the total |
| Trace and audit | Every read writes a metadata-only trace (`/v1/conversations`) and an audit entry `read conversation <id>` with message and withheld counts |
| No search | There is deliberately no full-text search: a search over raw data would answer "is there a chat mentioning X?" |

`CATO_CONVERSATIONS_STATS_SCAN` (default 5000) caps how many listing entries one statistics request reads; `CATO_CONVERSATIONS_MAX_MESSAGES` (default 500) caps messages per conversation.

## The support-default policy

| Data | Action |
|---|---|
| Names, organizations, places, e-mail, phone, address | pseudonymize |
| `customer_number`, `order_number`, `ticket_number`, `contract_number`, `invoice_number`, `tracking_number` (from custom patterns) | pseudonymize, so "the same order" stays recognisable |
| IBAN, credit card, tax and social security ids | redact |
| Dates, date of birth | generalize |
| Special categories (health, religion, ...) | message withheld from external models |
| Unknown types | redact |

Copy it, adapt it and save it as a new policy version (`POST /v1/policies`), then point `CATO_CONVERSATIONS_POLICY` at it.

## Evaluation before production

Detection is tuned on synthetic data. Support chats are informal: lowercase names, typos, order numbers, addresses in running text. Before production:

1. An authorized person exports a sample (e.g. 200 conversations) **inside** the protected environment.
2. Label names, contact data and your own identifiers in a corpus file (format: `packages/core/tests/corpus/de_support.yaml`).
3. Run `cato eval <corpus-dir>` with `CATO_CUSTOM_PATTERNS` set. No cloud model is involved.
4. Add patterns for every identifier format you find, repeat until recall is acceptable to your data-protection contact.

Known behaviour on chat text:

- **Self-introductions** ("mein Name ist …", "ich heiße …", "my name is …") are detected by rules, including lowercase names.
- **Bare names without a cue** depend on spaCy NER, which is weaker on lowercase chat text.
- **Over-redaction:** NER sometimes marks ordinary lowercase words in chats as names or organizations. That costs readability, not privacy.
- **Order numbers and other house formats** are only found with `CATO_CUSTOM_PATTERNS`.

## Dashboard

*Conversations* lists the metadata, shows statistics by prompt version and opens a conversation in its protected form. Opening one counts against your own quota and is audited like any other read.
