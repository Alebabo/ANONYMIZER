# OpenAnonymizer REST API

The Python API lives in `packages/core` (FastAPI). The full OpenAPI spec is at `/openapi.json`, with interactive docs at `/docs`.

## Quickstart (Docker)

```bash
cp .env.example .env
# Set ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL/_PASSWORD (first dashboard admin), optionally ANONYMIZER_ADMIN_KEYS and ANONYMIZER_VAULT_KEY
docker compose up -d --build
curl -s localhost:8080/health
```

- The image contains the spaCy models `de_core_news_lg` and `en_core_web_lg`. It is large (several GB) and the first build takes a while.
- Behind a TLS-intercepting proxy, pass the proxy's CA bundle as a build secret: `docker build --secret id=ca_bundle,src=ca.crt ...`.
- Container hardening:
  - Runs as a non-root user.
  - Read-only filesystem, no Linux capabilities.
  - Port only on `127.0.0.1`.
  - Vault, policies, traces, accounts and the audit log live in the `anonymizer-data` volume.

Without Docker:

```bash
cd packages/core
pip install -e .
python -m spacy download de_core_news_lg && python -m spacy download en_core_web_lg
ANONYMIZER_API_KEYS=... anonymizer-api          # binds to 127.0.0.1:8080
```

## Authentication

- **Header:** `Authorization: Bearer <key>` or `X-API-Key: <key>`. The same header carries dashboard session tokens.
- **API keys** are created in the dashboard (API Keys) or set as environment variables. Every key belongs to one organization; see [accounts.md](accounts.md).
- **User keys** (`ANONYMIZER_API_KEYS` or role `user`): scan, classify, anonymize, protect, documents, gateway, read traces and policies.
- **Admin keys** (`ANONYMIZER_ADMIN_KEYS` or role `admin`): in addition `POST /v1/restore`, `POST /v1/policies` and account management. If no admin key exists, restore and policy writes are disabled.
- **Environment keys are optional.** Without any key the API starts but refuses every request. Keys need at least 24 characters, and admin keys must differ from API keys.

## Endpoints

| Method | Path | Key | Function |
|---|---|---|---|
| GET | `/health` | – | Liveness |
| GET | `/v1/info` | API | Version, NER status, whether a vault is configured |
| POST | `/v1/scan` | API | Detect sensitive data (offsets, no values) |
| POST | `/v1/classify` | API | Risk per entity and document, with reasons |
| POST | `/v1/anonymize` | API | Anonymize; `namespace` enables reversible pseudonyms |
| POST | `/v1/protect` | API | Full pipeline with policy; returns `text` only when allowed |
| POST | `/v1/documents/protect` | API | Upload PDF/DOCX/TXT (multipart); DOCX comes back anonymized in place |
| POST | `/v1/chat/completions` | API | OpenAI-compatible gateway (see [gateway.md](gateway.md)) |
| GET | `/v1/traces`, `/v1/traces/{id}` | API | Metadata-only traces with decision history |
| GET | `/v1/metrics` | API | Aggregated privacy metrics |
| GET | `/v1/gateway` | API | Gateway configuration without credentials |
| POST | `/v1/restore` | Admin key | Resolve placeholders via the vault (audited) |
| GET | `/v1/policies` | API | Policies (latest version, hash, scope) |
| GET | `/v1/policies/{name}` | API | Policy (`?version=`, `?effective=true` resolves `extends`) |
| GET | `/v1/policies/{name}/history` | API | Versions with hashes |
| POST | `/v1/policies` | Admin | Save a new version (`version` = latest + 1) |
| POST | `/v1/policies/dry-run` | API | Compare a candidate policy against an active one |
| GET | `/v1/sources` | API | Connected conversation source and prompt store (type and host only) |
| GET | `/v1/conversations`, `/v1/conversations/{id}`, `/v1/conversations/stats`, `/v1/conversations/quota` | API | Protected customer conversations, see [conversations.md](conversations.md) |
| GET/POST | `/v1/prompts`, `/v1/prompts/{name}`, `.../history`, `.../diff` | API | Prompt versions and drafts, see [prompts.md](prompts.md) |
| POST | `/v1/prompts/{name}/labels` | Admin | Promote a prompt version (audited) |
| POST | `/mcp` | API | MCP over streamable HTTP when `ANONYMIZER_MCP_HTTP=1`, see [mcp.md](mcp.md) |

Login, members, API keys and the audit log: [accounts.md](accounts.md).

The gateway from the spec is implemented as the OpenAI-compatible `POST /v1/chat/completions`.

### Examples

```bash
KEY=anonymizer_...
curl -s localhost:8080/v1/protect -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"text":"Unser Mandant Herr Max Mustermann bittet um Rückruf.","destination":"external","namespace":"matter-17"}'
```

```json
{
  "outcome": "allow",
  "allowed": true,
  "text": "Unser Mandant Herr PERSON_001 bittet um Rückruf.",
  "risk": "critical",
  "decision": { "policy": "legal-default@v1", "policy_hash": "sha256:…", "entities": [ … ] },
  "classification": { … }
}
```

If the outcome is `review`, `local_only` or `block`, the response has `allowed: false` and `text: null`.

## Data protection in the API

- **Responses contain no detected raw values.** `scan` and `classify` return offsets; the client already has the text.
- **Validation errors (422) don't echo the input.** FastAPI's default behavior would return the submitted text in the error message.
- **The access log contains only** method, path, status, latency and request ID: no bodies, no query strings, no keys. `restore` and policy changes are logged as events, without content.
- **Every response carries an `X-Request-ID` header.** An incoming `X-Request-ID` is passed through if it is 1-64 characters of `A-Z a-z 0-9 _ . : -`; otherwise a new id is generated.
- **Text length is limited** by `ANONYMIZER_MAX_CHARS` (default 200,000). Longer texts get 413. Bodies whose `Content-Length` exceeds 4 bytes per allowed character plus 512 kB (document uploads: `ANONYMIZER_MAX_UPLOAD_BYTES` plus 64 kB) are refused with 413 before authentication and parsing. Chunked uploads carry no length; cap those at the reverse proxy.
- **`dry_run` on `/v1/protect`** returns the decision only: no text and no vault entries.
- **If the leak check fails**, the API returns 500 without any text.

## Configuration

See `.env.example` and `anonymizer.api.settings.Settings`.

## Not included yet

- **No TLS termination in the service.** Put a reverse proxy in front.
- **No rate limiting** except for failed logins.
- **Policies are shared by all organizations.** Traces, keys, members, the audit log and vault namespaces are separated per organization; policies are not. Only the default organization writes them.
