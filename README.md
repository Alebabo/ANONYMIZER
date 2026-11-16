# Cato — the open-source privacy layer for AI

Cato detects, classifies, anonymizes and controls sensitive data before AI models or agents process it: "Langfuse for privacy and data protection". Self-hosted, auditable, deterministic. First use case: protected access to production data over MCP. Verticals: legal work, recruiting. See [positioning](docs/positioning.md).

**Status:** Phase 1 (functional core) is implemented and tested on synthetic data. It has not been validated on real legal documents yet, and it is not a compliance certification.

## Quickstart

```bash
cp .env.example .env            # set the first admin and the keys (generator commands are in the file)
docker compose up -d --build    # API on 127.0.0.1:8080, spaCy models included
curl -s localhost:8080/health
docker compose exec api cato seed-demo   # optional: synthetic demo traces for the dashboard
```

```bash
curl -s localhost:8080/v1/protect -H "Authorization: Bearer $CATO_API_KEY" -H 'Content-Type: application/json' \
  -d '{"text":"Unser Mandant Herr Max Mustermann bittet um Rückruf.","destination":"external"}'
# -> "text": "Unser Mandant Herr PERSON_001 bittet um Rückruf.", "outcome": "allow"
```

## Repository layout

| Path | Content |
|---|---|
| `packages/core/` | Python package `cato-core`: engine, CLI (`cato`), REST API (`cato-api`), MCP server (`cato-mcp`), Dockerfile |
| `sdk/python/` | Python client `cato-sdk` (`from cato_sdk import Cato`) |
| `app/`, `components/`, `lib/` | Next.js dashboard (Langfuse-derived design, mobile-ready) with login: overview, gateway, privacy, traces, conversations, metrics, policies, prompts, API keys, integrations, settings, members, audit log |
| `examples/support/` | Synthetic support chats and example detection patterns |
| `docs/` | Documentation |

## Documentation

- [Positioning](docs/positioning.md): market, use cases, competitors, risks
- [API & self-hosting](docs/API.md)
- [Gateway](docs/gateway.md): OpenAI-compatible, local routing, traces & metrics
- [Detection](docs/detection.md): DE/EN, rules + spaCy NER, context signals, roles
- [Classification](docs/classification.md): low / sensitive / critical with reasons
- [Anonymization & vault](docs/anonymization.md): pseudonymization, encrypted re-identification vault
- [Policies](docs/policies.md): deterministic YAML policies, versioning, dry run
- [Accounts & audit log](docs/accounts.md): login, roles, organization scope, API keys, hash-chained audit log
- [MCP server](docs/mcp.md): `cato-mcp` (stdio) and `/mcp` (HTTP) for Claude, Cursor & other agents, with protected document access
- [Conversations](docs/conversations.md): protected access to customer chats (JSONL, HTTP contract, Langfuse) with quota, k-anonymity and audit
- [Prompts](docs/prompts.md): versions, labels, drafts from agents, promotion by people

## Customer chats and prompts for AI agents

Cato can run next to production and give Claude Code or Cursor protected access to customer conversations and prompt management, without the agent ever seeing raw customer data:

```bash
CATO_API_KEYS=cato_demo_key_change_me_0123456789 CATO_MCP_HTTP=1 CATO_PROMPTS=local \
CATO_SOURCE=jsonl CATO_SOURCE_PATH=examples/support/conversations.jsonl \
CATO_CUSTOM_PATTERNS=examples/support/patterns.yaml cato-api
claude mcp add --transport http cato http://127.0.0.1:8080/mcp \
  --header "Authorization: Bearer cato_demo_key_change_me_0123456789"
```

Details, guarantees and the checks required before production: [docs/conversations.md](docs/conversations.md). Step-by-step handover for testing and adapting it in a company environment (German): [HANDOVER.md](HANDOVER.md).

## Development

```bash
cd packages/core
pip install -e ".[dev]"
python -m spacy download de_core_news_lg && python -m spacy download en_core_web_lg
pytest                       # incl. corpus, leak and API tests
cato eval tests/corpus       # detection/classification against the synthetic corpus

# Dashboard: demo mode with example data, or live with login when CATO_API_URL is set
npm install
npm run dev                                         # demo mode
CATO_API_URL=http://localhost:8080 npm run dev      # live: sign in with a Cato user
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
- **Cato provides technical safeguards.** It does not guarantee GDPR compliance or the professional secrecy obligations of lawyers.

## Roadmap

Plan for the MCP proxy and the next phases: [roadmap.md](roadmap.md).

- **Phase 2:** streaming in the gateway, TypeScript SDK, native Anthropic endpoint, OAuth for remote MCP (done: gateway, MCP over stdio and HTTP, documents, Python SDK, conversation access, prompt management)
- **Phase 3:** review queue with approvals, graphical policy editor (done: traces, metrics, dashboard on live data, API key management in the UI)
- **Phase 4:** SSO/MFA, finer RBAC, PostgreSQL, Helm (done: organizations, login, roles, hash-chained audit log)

License: Apache-2.0. Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
