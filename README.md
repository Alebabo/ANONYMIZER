# OpenAnonymizer — the open-source privacy layer for AI

OpenAnonymizer detects, classifies, anonymizes and controls sensitive data before AI models or agents process it: "Langfuse for privacy and data protection". Self-hosted, auditable, deterministic. First use case: protected access to production data over MCP. Verticals: legal work, recruiting.

**Status:** Phase 1 (functional core) is implemented and tested on synthetic data. It has not been validated on real legal documents yet, and it is not a compliance certification.

## Quickstart

```bash
cp .env.example .env            # set the first admin and the keys (generator commands are in the file)
docker compose up -d --build    # API on 127.0.0.1:8080, spaCy models included
curl -s localhost:8080/health
docker compose exec api anonymizer seed-demo   # optional: synthetic demo traces for the dashboard
```

```bash
curl -s localhost:8080/v1/protect -H "Authorization: Bearer $ANONYMIZER_API_KEY" -H 'Content-Type: application/json' \
  -d '{"text":"Unser Mandant Herr Max Mustermann bittet um Rückruf.","destination":"external"}'
# -> "text": "Unser Mandant Herr PERSON_001 bittet um Rückruf.", "outcome": "allow"
```

## Repository layout

| Path | Content |
|---|---|
| `packages/core/` | Python package `anonymizer-core`: engine, CLI (`anonymizer`), REST API (`anonymizer-api`), MCP server (`anonymizer-mcp`), Dockerfile |
| `sdk/python/` | Python client `anonymizer-sdk` (`from anonymizer_sdk import OpenAnonymizer`) |
| `app/`, `components/`, `lib/` | Next.js dashboard with login, three tabs: **Chat** (type a text, see what the model receives), **Traces** (every use via API, MCP, Chat or CSV, with channel and key) and **CSV** (upload a test file, hide columns). Settings: policies (with test, also via API), API keys, members, audit log |
| `examples/support/` | Example detection patterns (order numbers, customer ids, ticket ids) |
| `docs/` | Documentation |

## Documentation

- [API & self-hosting](docs/API.md)
- [Detection](docs/detection.md): DE/EN, rules + spaCy NER, context signals, roles
- [Classification](docs/classification.md): low / sensitive / critical with reasons
- [Anonymization & vault](docs/anonymization.md): pseudonymization, encrypted re-identification vault
- [Policies](docs/policies.md): deterministic YAML policies, versioning, dry run
- [Accounts & audit log](docs/accounts.md): login, roles, organization scope, API keys, hash-chained audit log
- [MCP server](docs/mcp.md): `anonymizer-mcp` (stdio) and `/mcp` (HTTP) for Claude, Cursor & other agents, with protected document access

## One model, three ways to use it

The same model and the same saved policy serve every channel; every call is a trace with channel (`api`, `mcp`, `dashboard`) and key name or user:

- **Chat tab** in the dashboard: paste a text, get what an AI model would receive.
- **REST:** `POST /v1/protect` (also `/v1/scan`, `/v1/anonymize`; policy test: `POST /v1/policies/{name}/test`).
- **MCP:** `claude mcp add --transport http anonymizer <url>/mcp --header "Authorization: Bearer <key>"`, tool `anonymize_content`.

Traces can be filtered by channel (`GET /v1/traces?client=mcp`).

Step-by-step handover for testing and adapting OpenAnonymizer in a company environment (German): [HANDOVER.md](HANDOVER.md).

## Development

```bash
cd packages/core
pip install -e ".[dev]"
python -m spacy download de_core_news_lg && python -m spacy download en_core_web_lg
pytest                       # incl. corpus, leak and API tests
anonymizer eval tests/corpus       # detection/classification against the synthetic corpus

# Dashboard: demo mode with example data, or live with login when ANONYMIZER_API_URL is set
npm install
npm run dev                                         # demo mode
ANONYMIZER_API_URL=http://localhost:8080 npm run dev      # live: sign in with a OpenAnonymizer user
```

## Security principles

- **Determinism:** policies are evaluated deterministically. No LLM decides whether critical data is passed on.
- **Fail closed:**
  - Unknown types are redacted.
  - Uncertain detections are never downgraded.
  - Degraded detection (NER missing) never produces "low".
- **Critical data** never goes to external models unchanged.
- **The re-identification mapping** is encrypted and stored separately from the key. It is never part of a result or a log.
- **No raw data** in logs, error messages or API responses.
- **OpenAnonymizer provides technical safeguards.** It does not guarantee GDPR compliance or the professional secrecy obligations of lawyers.

## Roadmap

Next phases: [roadmap.md](roadmap.md).

- **Phase 2:** TypeScript SDK, OAuth for remote MCP (done: MCP over stdio and HTTP, documents, Python SDK). Removed in November 2026 because they had no UI: OpenAI-compatible gateway, MCP proxy, conversation access, prompt management (see git history)
- **Phase 3:** review queue with approvals, graphical policy editor (done: traces, metrics, dashboard on live data, API key management in the UI)
- **Phase 4:** SSO/MFA, finer RBAC, PostgreSQL, Helm (done: organizations, login, roles, hash-chained audit log)

License: Apache-2.0. Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
