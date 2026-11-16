# Roadmap: from MCP server to privacy layer for production MCPs

Basis: [docs/positioning.md](docs/positioning.md). Wedge: production MCPs. Verticals (legal, recruiting) come later as policy packs.

## 1. Starting point (what exists)

| Area | Status |
|---|---|
| MCP server | `cato-mcp` (stdio) and `/mcp` (HTTP, bearer key). Tools: scan, classify, anonymize, policy check, report, protected documents, conversations, prompts |
| Guarantees | No restore over MCP; no policy, destination or namespace arguments; read-only annotations; generic tool errors; content marked as data |
| Sources | `jsonl`, `http` (two-endpoint contract), `langfuse` |
| Protection | Detection DE/EN (rules + spaCy), deterministic YAML policies (`legal-default`, `support-default`), vault, quotas, k-anonymity, opaque ids |
| Operations | Hash-chained audit log, traces, dashboard, OpenAI-compatible gateway, Python SDK, Docker |
| Gaps | No proxy for **third-party MCP servers**; no SQL source; dry run only in the CLI; no OAuth; scan/anonymize calls not audited; only plain text in `read_document_protected`; recall on real data unmeasured |

**Core gap:** today Cato only protects data that flows through **its own** tools. Teams already use MCP servers for Postgres, Jira, Zendesk, Slack and GitHub. The product is the layer **in front of** these servers.

## 2. Target

```
Claude Code / Cursor / Desktop
        │  MCP (HTTP, key or OAuth)
        ▼
Cato MCP Proxy  ── policy per upstream and tool, audit, dry run
   ├─ upstream: postgres-mcp   (stdio / HTTP)
   ├─ upstream: jira-mcp
   ├─ upstream: cato built-ins (documents, conversations, prompts)
   └─ ...
```

- The client sees **one** MCP endpoint. Tool names are prefixed by upstream (`jira__search_issues`).
- Every tool **result** goes through detect → classify → policy → pseudonymize before it reaches the client.
- Every tool **call argument** is checked. Placeholders are resolved to real values only when the policy allows it per upstream; otherwise the call is refused.
- Configuration is a YAML file, not code.

## 3. Phases

### Phase A: MCP proxy MVP (4–6 weeks)

| # | Package | Content | Done when |
|---|---|---|---|
| A1 | Upstream client | Connect to MCP servers over stdio and HTTP, list tools, forward calls (official MCP SDK) | Postgres MCP and a filesystem MCP work through Cato |
| A2 | Tool registry | Prefixing, allow/deny list per upstream and tool, hide write tools by default | Write tools are invisible unless enabled |
| A3 | Result filter | Text, JSON and resource content through the pipeline; JSON field by field (keys stay, values are protected) | No raw value from the synthetic corpus in any result |
| A4 | Argument handling | Detect PII in arguments; placeholder resolution only with `resolve_placeholders: true` per upstream, audited | Model cannot exfiltrate restore through a tool call |
| A5 | Dry run | `mode: observe` per upstream: pass results through unchanged, log what would have been protected (types and counts only) | Dashboard shows "would have redacted" without blocking |
| A6 | Config | `cato-proxy.yaml`: upstreams, mode, policy, namespace, quotas | One file, one `claude mcp add` |
| A7 | Audit | Each proxied call: actor, upstream, tool, outcome, entity counts. Also for scan/anonymize | Audit log covers every MCP call |

Example config:

```yaml
upstreams:
  postgres:
    command: ["postgres-mcp", "--readonly"]
    env: { DATABASE_URL: "${PROD_REPLICA_URL}" }
    mode: enforce            # observe | enforce
    policy: support-default
    tools: { allow: ["query", "list_tables", "describe_table"] }
  jira:
    url: https://jira-mcp.internal/mcp
    headers: { Authorization: "Bearer ${JIRA_TOKEN}" }
    mode: observe
    resolve_placeholders: false
```

### Phase B: Quality and trust (in parallel, 4–8 weeks)

| # | Package | Content |
|---|---|---|
| B1 | GLiNER as a second NER | Run it next to spaCy. Union of hits (fail closed). Lowercase chat text and EU entities |
| B2 | EU entities | BIC, depot/account numbers, licence plates, social security numbers AT/CH, UID numbers |
| B3 | Public benchmark | `cato bench`: Cato vs. Presidio vs. LLM redaction on German data (German LER plus a synthetic chat/ticket corpus). Recall per type, published in the repo |
| B4 | Structured data | Column classification for SQL results: protect by column name and content, cached per table |
| B5 | Real sample | Evaluation at the design partner, offline, by an authorized person |

### Phase C: Enterprise readiness (6–10 weeks)

| # | Package | Content |
|---|---|---|
| C1 | OAuth for remote MCP | Needed for Claude Desktop and claude.ai connectors |
| C2 | SSO/MFA, RBAC | OIDC/SAML, roles per upstream |
| C3 | PostgreSQL, Helm | Replace SQLite for multi-instance operation |
| C4 | Latency budget | p95 overhead < 150 ms per call (rules only < 20 ms), measured in CI |
| C5 | Documents | PDF/DOCX in the proxy and `read_document_protected` |
| C6 | Compliance export | Report per period: which data types went to which model, blocked calls, policy versions |

### Phase D: Verticals (after a design partner)

- Policy packs `legal-de` (§ 203 StGB, case numbers, roles) and `hr-de` (AGG-relevant attributes, AI Act documentation).
- Paid: domain-tuned models, packs, SSO, support.

## 4. Order and rationale

1. **A1–A3, A5, A6** first. That is the minimal demo: "Hang Claude on your prod DB, see what Cato would protect". Observe mode lowers the barrier to adoption.
2. **B1, B3** in parallel. Without measurable quality, enforce mode is not credible.
3. **A4, A7** before the first enforce rollout.
4. **C** only with a concrete customer. Do not build enterprise features blindly.

## 5. Risks

- **Latency and availability:** the proxy is in the path. Mitigation: per-upstream timeouts, rules-only fast path, a health check per upstream.
- **JSON and SQL results:** names in free-text columns, IDs in keys. Mitigation: column classification (B4), fail closed for unknown structures.
- **Placeholder resolution in arguments** is a re-identification path. Off by default; enable only per upstream and audit it.
- **Upstream MCPs are untrusted:** tool descriptions can contain prompt injection. Mitigation: descriptions get the same data notice; tool names come from config, not from the upstream.
- **Scope:** no own LLM hosting, no chat UI. Cato stays a layer.

## 6. Prerequisites outside the code

Same as [plan.md section 4](plan.md): approval by security and data protection, contract with the model provider, a real-sample evaluation and a clear split of ownership with the employer (open-source core in this repo, company-specific adapters in theirs).
