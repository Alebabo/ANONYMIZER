# Positioning

## One line

Cato is the open-source privacy layer for AI: "Langfuse for privacy and data protection". It makes production data usable by LLMs and agents without raw personal data leaving the company network. It is self-hosted, auditable and deterministic.

## Core difference to Langfuse

Langfuse observes requests on the side. Cato sits **in the request path**. If Cato fails or is slow, the application stops. This raises the bar for latency, stability and trust. A dry-run mode (observe and report, do not block) lowers the barrier to adoption. It is the entry point.

## Place in the stack

```
Data sources (databases, chats, documents, tickets, mails)
        │
        ▼
Cato: detect → classify → policy → pseudonymize → audit → restore
        │      only placeholder data crosses this line
        ▼
Any LLM or agent (Claude, GPT, Mistral, local models)
```

Cato is model-agnostic. It does not host or brand models.

## What we take from Langfuse

- OSS core under a permissive license, `docker compose up` in minutes.
- SDKs (Python, TypeScript) and integrations (MCP, OpenAI-compatible gateway, LangChain, LlamaIndex).
- Cloud for convenience, **self-hosted enterprise** for regulated customers: SSO, RBAC, audit, support.
- A dashboard that shows which personal data went where, what was blocked and which policy applied.

## Use cases

| | Production MCPs | Legal work | Recruiting |
|---|---|---|---|
| Buyer | Developers, platform teams | Law firms, legal-tech vendors | HR, HR-tech vendors |
| Sales motion | Bottom-up, fast | Top-down, slow | Medium |
| Regulatory pressure | GDPR, internal policy, DORA/BAIT for banks | § 203 StGB, § 43e BRAO | GDPR, AGG, **EU AI Act high-risk (Annex III)** |
| Role | **Wedge** | Vertical (policy pack) | Vertical (policy pack) |

- **Production MCPs (first):** teams want Claude Code or Cursor on prod data (chats, tickets, databases). Cato as the only MCP endpoint next to prod is clear, quick to test and spreads bottom-up.
- **Legal and recruiting (later):** prebuilt entity sets, rules and policies per industry as paid policy packs.
- **Recruiting caveat:** AI in candidate selection is high-risk under the AI Act. The need is documentation and bias control more than anonymization. This widens scope; don't start there.

## Differentiation

- **Self-hosted first.** Banks and law firms do not buy cloud anonymization.
- **German/EU entities:** IBAN, tax ID, BIC, case numbers, depot numbers, licence plates. Most tools are US-centric.
- **Deterministic policies:** no LLM decides whether critical data is passed on. Recognition uses rules plus small NER models (spaCy, GLiNER). These classify and do not generate.
- **Audit and policy as the purchase reason:** who sent what to which model, when. Compliance buys this, not detection alone.
- **Open core:** the engine can be inspected by IT security. That is a trust argument.

## Open core vs. paid

| Open source | Paid |
|---|---|
| Detection engine (rules + NER), anonymization, vault | Domain-tuned models (legal, banking, HR) |
| Gateway, MCP server, Python SDK | Policy packs per industry |
| Dashboard basics, dry run | SSO/MFA, fine-grained RBAC, retention, compliance reports |
| Self-hosting | Support, SLAs, certifications (ISO 27001, BSI C5) |

Detection quality is the same in OSS and paid. A weaker free engine would give self-hosters worse privacy, which is a poor sales argument.

## Competitive landscape

Based on knowledge at the time of writing. Verify before decisions.

- **LLM/MCP gateways with PII filters:** Portkey, Lasso Security, Kong AI Gateway, Cloudflare AI Gateway, LiteLLM (Presidio integration), TrueFoundry, Helicone.
- **PII engines:** Microsoft Presidio (OSS), Private AI, Protecto, Skyflow, Tonic Textual, Gretel, GLiNER-PII, Piiranha.
- **LLM security/guardrails:** Lakera, Prompt Security, Protect AI (LLM Guard), NVIDIA NeMo Guardrails, Guardrails AI, Nightfall.
- **Enterprise DLP:** Microsoft Purview, Google Sensitive Data Protection, AWS Comprehend / Bedrock Guardrails, Netskope, Zscaler, Palo Alto.
- **DACH/EU platforms:** Aleph Alpha, Langdock, nele.ai. Legal tools (e.g. Noxtua, Bryter, Libra) have anonymization as a feature, not a product.

**Gap for Cato:** OSS + self-hosted + MCP-native + German/EU entities + audit dashboard + dry run.

**Main threat:** LiteLLM plus Presidio is free and "good enough". Cato must be measurably better on recall for German/EU data, MCP support and audit UX.

## Risks

- **In-path trust:** one leaked IBAN burns the product. Public benchmarks are mandatory.
- **Narrow window:** MCP gateways are a crowded, fast-moving space.
- **Regulated sales cycles:** 12–24 months in banks (outsourcing review, pen tests). A reference customer is required.
- **Shrinking need:** if LLM vendors offer EU hosting and secrecy commitments by default, pure anonymization loses value. Audit, policy and tenant separation keep the value.
- **Pseudonymization is not anonymization:** context can re-identify people. Under GDPR the output stays personal data. Communicate this honestly.
- **Model origin:** do not rebrand third-party models (e.g. Chinese open-weight models) as Cato models. Licenses require attribution and DORA requires a known supply chain. Use EU/US base models as defaults; offer others transparently.

## Next steps

1. MCP proxy with dry run and dashboard as the public MVP (largely in place, see [conversations](conversations.md), [MCP](mcp.md)).
2. Detection for German/EU entities: rules plus GLiNER next to spaCy.
3. Public benchmark: Cato vs. Presidio vs. LLM-based redaction on German data (e.g. the German LER dataset).
4. Design partner in a regulated company, with approval from security and data protection.
5. Then policy packs for legal and HR.
