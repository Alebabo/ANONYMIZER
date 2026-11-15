# Cato — Privacy Infrastructure for Legal AI

Cato detects, classifies, anonymizes and controls sensitive legal information before AI models or agents process it. Cato is an infrastructure component that legal-tech products integrate. It is not a legal-tech application itself.

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
| `app/`, `components/`, `lib/` | Next.js dashboard (Langfuse-derived design, mobile-ready) with login: overview, gateway, privacy, traces, metrics, policies, API keys, integrations, settings, members, audit log |
| `docs/` | Documentation |

## Documentation

- [API & self-hosting](docs/API.md)
- [Gateway](docs/gateway.md): OpenAI-compatible, local routing, traces & metrics
- [Detection](docs/detection.md): DE/EN, rules + spaCy NER, context signals, roles
- [Classification](docs/classification.md): low / sensitive / critical with reasons
- [Anonymization & vault](docs/anonymization.md): pseudonymization, encrypted re-identification vault
- [Policies](docs/policies.md): deterministic YAML policies, versioning, dry run
- [Accounts & audit log](docs/accounts.md): login, roles, organization scope, API keys, hash-chained audit log
- [MCP server](docs/mcp.md): `cato-mcp` for Claude, Cursor & other agents, with protected document access

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

- **Phase 2:** streaming in the gateway, TypeScript SDK, native Anthropic endpoint (done: gateway, MCP, documents, Python SDK)
- **Phase 3:** review queue with approvals, graphical policy editor (done: traces, metrics, dashboard on live data, API key management in the UI)
- **Phase 4:** SSO/MFA, finer RBAC, PostgreSQL, Helm (done: organizations, login, roles, hash-chained audit log)

License: Apache-2.0. Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
