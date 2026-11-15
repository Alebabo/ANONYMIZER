# Cato REST API

The Python API lives in `packages/core` (FastAPI). The full OpenAPI spec is at `/openapi.json`, with interactive docs at `/docs`.

## Quickstart (Docker)

```bash
cp .env.example .env
# Fill in CATO_API_KEYS, optionally CATO_ADMIN_KEYS and CATO_VAULT_KEY (generator commands are in the file)
docker compose up -d --build
curl -s localhost:8080/health
```

- The image contains the spaCy models `de_core_news_lg` and `en_core_web_lg`. It is large (several GB) and the first build takes a while.
- Behind a TLS-intercepting proxy, pass the proxy's CA bundle as a build secret: `docker build --secret id=ca_bundle,src=ca.crt ...`.
- Container hardening:
  - Runs as a non-root user.
  - Read-only filesystem, no Linux capabilities.
  - Port only on `127.0.0.1`.
  - Vault and policies live in the `cato-data` volume.

Without Docker:

```bash
cd packages/core
pip install -e .
python -m spacy download de_core_news_lg && python -m spacy download en_core_web_lg
CATO_API_KEYS=... cato-api          # binds to 127.0.0.1:8080
```

## Authentication

- **Header:** `Authorization: Bearer <key>` or `X-API-Key: <key>`.
- **`CATO_API_KEYS`:** scan, classify, anonymize, protect, read policies.
- **`CATO_ADMIN_KEYS`:** in addition `POST /v1/restore` and `POST /v1/policies`. If no admin keys are set, these endpoints are disabled.
- **The service refuses to start without API keys.** Keys need at least 24 characters, and admin keys must differ from API keys.

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
| POST | `/v1/restore` | Admin | Resolve placeholders via the vault |
| GET | `/v1/policies` | API | Policies (latest version, hash, scope) |
| GET | `/v1/policies/{name}` | API | Policy (`?version=`, `?effective=true` resolves `extends`) |
| GET | `/v1/policies/{name}/history` | API | Versions with hashes |
| POST | `/v1/policies` | Admin | Save a new version (`version` = latest + 1) |
| POST | `/v1/policies/dry-run` | API | Compare a candidate policy against an active one |

The gateway from the spec is implemented as the OpenAI-compatible `POST /v1/chat/completions`.

### Examples

```bash
KEY=cato_...
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
- **Every response carries an `X-Request-ID` header.** An incoming `X-Request-ID` is passed through.
- **Text length is limited** by `CATO_MAX_CHARS` (default 200,000). Longer texts get 413.
- **If the leak check fails**, the API returns 500 without any text.

## Configuration

See `.env.example` and `cato.api.settings.Settings`.

## Not included yet

- **No TLS termination in the service.** Put a reverse proxy in front.
- **No rate limiting.**
- **No multi-tenancy at the key level.** Every key sees all policies; `tenant`/`team` in the request only select the policy. Phase 4.
