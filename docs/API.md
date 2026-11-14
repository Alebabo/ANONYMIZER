# Cato API (early backend)

Stateless, same-origin text endpoints. Requests are processed in memory and are not intentionally persisted or logged by these handlers.

## POST /api/v1/analyze
Request: { "text": "Please contact max@example.com under § 280 BGB." }

Returns entity-level findings, character offsets, counts, limitations, and \`safeToShare: false\`.

## POST /api/v1/redact
Request: { "text": "Please contact max@example.com", "consentedGreyIds": [] }

Critical findings are always redacted. Grey findings are redacted unless their finding IDs are included in \`consentedGreyIds\`. Uncritical matches remain.

## Limitations and production blockers
- Deterministic regex baseline only; not a complete PII detector or legal-grade anonymisation system.
- Person names, organisations, free-form addresses, case facts and contextual identifiers may be missed.
- Unmatched content is not certified as Uncritical.
- Every response deliberately sets \`safeToShare: false\` and \`reviewRequired: true\`. Do not use this as an automatic release gate to LLM providers or MCP tools.
- No authentication, tenant isolation, persistent document store, encryption-at-rest, audit log, malware scanning, file parser, rate limiting, NER worker or provider integration.
- Text only; file uploads are not accepted by these endpoints.

Before production use, add authentication/authorization, secure storage, isolated parsing and NER workers, policy tests, adversarial evaluations, payload-safe observability, and independent post-redaction validation. Do not submit confidential legal documents to this prototype.
