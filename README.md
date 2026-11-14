# Cato — Privacy Infrastructure for Legal AI

Cato detects, classifies, anonymizes and controls sensitive legal information before AI models or agents process it.

## Repository layout
- `packages/core/` — Python privacy engine (`cato-core`). Implemented: detection ([docs/detection.md](docs/detection.md)), classification ([docs/classification.md](docs/classification.md)), anonymization + vault ([docs/anonymization.md](docs/anonymization.md)), policy engine ([docs/policies.md](docs/policies.md)).
- `app/`, `components/` — Next.js dashboard (Langfuse-derived design, example data only).
- `app/api/v1/*` — legacy TypeScript prototype endpoints, to be replaced by the Python API.

License: Apache-2.0. Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Legacy TypeScript prototype
- Minimal upload/text-entry interface and document list.
- Three classification levels: CRITICAL, GREY, UNCRITICAL.
- Grey consent controls are UI-only and do not authorize any external transfer.
- Demo findings are illustrative sample data.
- The browser UI is still a prototype; selected files are not uploaded or parsed.
- Stateless text API: `POST /api/v1/analyze` and `POST /api/v1/redact`.
- Initial rule-based detection for IBANs, German tax IDs, emails, phone numbers, postcodes and selected legal citations.
- Critical matches are always redacted; Grey matches require explicit request-specific consent to remain.
- API responses always require human review and set `safeToShare: false`.

## API
See [docs/API.md](docs/API.md) for request examples and limitations. The API accepts text only (max. 100,000 characters) and does not persist request bodies.

## Run
```bash
npm install
npm run dev
```

## Next milestones
1. Secure upload API with type/size validation and private storage.
2. Isolated PDF/DOCX/TXT parsing worker.
3. Hybrid detection: deterministic rules, NER and contextual classifier.
4. Policy enforcement: Critical always blocked; Grey requires explicit per-request consent; Uncritical may pass.
5. Redaction plus independent post-redaction validation before provider calls.
6. MCP/API proxy only after the privacy boundary is tested.

## Security principles
- Unknown/low-confidence data must never silently pass as Uncritical.
- Critical is non-overridable by UI consent.
- Keep re-identification mappings encrypted and separately stored.
- Do not send raw documents or prompts to external LLMs before redaction and validation.
- This prototype is not production-ready and is not a compliance certification.
