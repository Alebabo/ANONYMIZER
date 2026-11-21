# OpenAnonymizer as an MCP server

`anonymizer-mcp` provides OpenAnonymizer as a Model Context Protocol server (stdio). AI agents in Claude Desktop, Claude Code, Cursor or other MCP clients can use it to check and anonymize legal content before they process it.

## Threat model

Behind an MCP client there is usually a **cloud LLM**. Everything a tool returns goes to the provider. This leads to the design rules:

| Risk | Protection |
|---|---|
| Tool results contain raw data | `scan`/`classify`/`report` return only types, offsets, risks and reasons. `anonymize` returns text only if the policy allows it |
| The model weakens the policy via an argument | No tool has `destination`, `policy` or `namespace` parameters. The operator sets them in the environment. Tested |
| Re-identification through the agent | **No restore tool.** Restore only happens in the protected environment via the admin API |
| Agent reads client files raw | `read_document_protected` returns only the anonymized version. Use it instead of raw file tools |
| Path traversal / symlink escape | Access only inside `ANONYMIZER_MCP_ROOT`, paths resolved including symlinks, only text formats. Tested |
| Prompt injection in documents | Results carry a notice that the content is data, not instructions. The server instructions say so too |
| Unwanted side effects | All tools are marked read-only and not open-world. No network access, no write access |

**Limitation:** if the agent already has a document's raw text in its context (e.g. pasted by the user), it was already sent to the provider. OpenAnonymizer only protects what goes through OpenAnonymizer. For client documents that means: use the folder plus `read_document_protected`, not copy-paste.

## Tools

| Tool | Returns |
|---|---|
| `scan_document(text, language?)` | Entity types, offsets, risk, role, signals |
| `classify_content(text, language?)` | Risk per entity and document, with reasons |
| `anonymize_content(text, language?)` | Anonymized text, or `text: null` with the reason |
| `check_privacy_policy(text, language?)` | Policy outcome and actions per type, no text |
| `get_privacy_report(text, language?)` | Markdown report without raw values |
| `list_documents()` | Readable files in `ANONYMIZER_MCP_ROOT` (only if configured) |
| `read_document_protected(path, language?)` | Anonymized file contents or refusal (only if configured) |

## Configuration (operator)

| Variable | Meaning |
|---|---|
| `ANONYMIZER_MCP_DESTINATION` | `external` (default) or `local`. Use `local` only if the client runs exclusively on a local model |
| `ANONYMIZER_MCP_POLICY` | Path to a policy YAML. Default: stdio `banking-default`; over HTTP (`/mcp` of the API) the API's saved default policy, so policy changes in the dashboard apply to MCP right away |
| `ANONYMIZER_MCP_ROOT` | Document folder for `read_document_protected`. Without it, the file tools are disabled |
| `ANONYMIZER_MCP_MAX_CHARS` | Max. characters per text/file (200,000) |
| `ANONYMIZER_VAULT_KEY`, `ANONYMIZER_VAULT_PATH`, `ANONYMIZER_MCP_NAMESPACE` | Optional: consistent pseudonyms across calls (e.g. one namespace per matter) |
| `ANONYMIZER_CUSTOM_PATTERNS` | Optional: deployment-specific patterns (see [detection.md](detection.md)) |

## Setup

Install:

```bash
pip install -e packages/core
python -m spacy download de_core_news_lg && python -m spacy download en_core_web_lg
```

**Claude Code:**

```bash
claude mcp add anonymizer --env ANONYMIZER_MCP_ROOT=/path/to/matter-folder -- anonymizer-mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "anonymizer": {
      "command": "anonymizer-mcp",
      "env": {
        "ANONYMIZER_MCP_ROOT": "/Users/kanzlei/Akten/2024-017",
        "ANONYMIZER_MCP_DESTINATION": "external"
      }
    }
  }
}
```

**Docker** (same image as the API, models included):

```bash
docker run -i --rm -v /path/to/matter-folder:/docs:ro -e ANONYMIZER_MCP_ROOT=/docs anonymizer-api:local anonymizer-mcp
```

## Recommended agent workflow

1. `list_documents` shows the files in the matter folder.
2. `read_document_protected("klage.txt")` returns the anonymized text with `PERSON_001`, `CASE_NUMBER_001`, ...
3. The agent works only with the placeholders.
4. If the result is `review` / `local_only` / `block`, the agent stops and asks the user.
5. A lawyer restores the original names in the final document via the admin API or `anonymizer restore`, outside the agent.

## Playground datasets (HTTP only)

Over HTTP (`/mcp` of the API) the server also offers the CSV uploads from the dashboard (CSV tab):

| Tool | Returns |
|---|---|
| `list_datasets()` | Id, name, visible columns, row count |
| `query_dataset(dataset_id, query?, columns?, limit?, offset?)` | Protected rows; withheld values as `[WITHHELD]`. Hidden columns are never searched or sent |

Not available over MCP on purpose: restore, and every argument that could change policy, destination or namespace.

## HTTP transport (remote MCP)

`ANONYMIZER_MCP_HTTP=1` on the API serves the same tools at `/mcp` (streamable HTTP, stateless, JSON responses). Every request needs a OpenAnonymizer API key, `Authorization: Bearer <key>` or `X-API-Key`. The key decides the organization and the actor in traces and the audit log. Requests without a valid key get 401 before they reach the MCP server.

```bash
claude mcp add --transport http anonymizer https://anonymizer.internal.example/mcp \
  --header "Authorization: Bearer anonymizer_..."
```

Cursor (`.cursor/mcp.json`):

```json
{ "mcpServers": { "anonymizer": { "url": "https://anonymizer.internal.example/mcp",
                            "headers": { "Authorization": "Bearer anonymizer_..." } } } }
```

- Put TLS in front (reverse proxy), as for the rest of the API.
- `ANONYMIZER_MCP_ALLOWED_HOSTS=anonymizer.internal.example` enables DNS-rebinding protection for those hosts.
- One key per person: traces and the audit log are per key.
- Claude Desktop and claude.ai custom connectors need OAuth; that is not included yet. Claude Code, Cursor and other clients that send a header work.

## Not included yet

- **Only plain text formats** for `read_document_protected`. PDF/DOCX go through `POST /v1/documents/protect`.
- **No OAuth** for remote MCP (see above).
- **Audit:** playground queries are audited; `scan`/`anonymize` calls are traced, not audited.

## Traces

Over HTTP every tool call is a trace with `client: "mcp"` and the key name as `actor`. `anonymize_content`
writes a full trace (entities, policy, outcome, latency); other tools record name, latency and status.
Filter in the dashboard (Traces → MCP) or with `GET /v1/traces?client=mcp`.

