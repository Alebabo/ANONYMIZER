# Cato as an MCP server

`cato-mcp` provides Cato as a Model Context Protocol server (stdio). AI agents in Claude Desktop, Claude Code, Cursor or other MCP clients can use it to check and anonymize legal content before they process it.

## Threat model

Behind an MCP client there is usually a **cloud LLM**. Everything a tool returns goes to the provider. This leads to the design rules:

| Risk | Protection |
|---|---|
| Tool results contain raw data | `scan`/`classify`/`report` return only types, offsets, risks and reasons. `anonymize` returns text only if the policy allows it |
| The model weakens the policy via an argument | No tool has `destination`, `policy` or `namespace` parameters. The operator sets them in the environment. Tested |
| Re-identification through the agent | **No restore tool.** Restore only happens in the protected environment via the admin API |
| Agent reads client files raw | `read_document_protected` returns only the anonymized version. Use it instead of raw file tools |
| Path traversal / symlink escape | Access only inside `CATO_MCP_ROOT`, paths resolved including symlinks, only text formats. Tested |
| Prompt injection in documents | Results carry a notice that the content is data, not instructions. The server instructions say so too |
| Unwanted side effects | All tools are marked read-only and not open-world. No network access, no write access |

**Limitation:** if the agent already has a document's raw text in its context (e.g. pasted by the user), it was already sent to the provider. Cato only protects what goes through Cato. For client documents that means: use the folder plus `read_document_protected`, not copy-paste.

## Tools

| Tool | Returns |
|---|---|
| `scan_document(text, language?)` | Entity types, offsets, risk, role, signals |
| `classify_content(text, language?)` | Risk per entity and document, with reasons |
| `anonymize_content(text, language?)` | Anonymized text, or `text: null` with the reason |
| `check_privacy_policy(text, language?)` | Policy outcome and actions per type, no text |
| `get_privacy_report(text, language?)` | Markdown report without raw values |
| `list_documents()` | Readable files in `CATO_MCP_ROOT` (only if configured) |
| `read_document_protected(path, language?)` | Anonymized file contents or refusal (only if configured) |

## Configuration (operator)

| Variable | Meaning |
|---|---|
| `CATO_MCP_DESTINATION` | `external` (default) or `local`. Use `local` only if the client runs exclusively on a local model |
| `CATO_MCP_POLICY` | Path to a policy YAML. Default: `legal-default` |
| `CATO_MCP_ROOT` | Document folder for `read_document_protected`. Without it, the file tools are disabled |
| `CATO_MCP_MAX_CHARS` | Max. characters per text/file (200,000) |
| `CATO_VAULT_KEY`, `CATO_VAULT_PATH`, `CATO_MCP_NAMESPACE` | Optional: consistent pseudonyms across calls (e.g. one namespace per matter) |
| `CATO_SOURCE`, `CATO_PROMPTS`, `CATO_CUSTOM_PATTERNS`, `CATO_CONVERSATIONS_*` | Optional: conversation and prompt tools (stdio reads them from the environment) |

## Setup

Install:

```bash
pip install -e packages/core
python -m spacy download de_core_news_lg && python -m spacy download en_core_web_lg
```

**Claude Code:**

```bash
claude mcp add cato --env CATO_MCP_ROOT=/path/to/matter-folder -- cato-mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cato": {
      "command": "cato-mcp",
      "env": {
        "CATO_MCP_ROOT": "/Users/kanzlei/Akten/2024-017",
        "CATO_MCP_DESTINATION": "external"
      }
    }
  }
}
```

**Docker** (same image as the API, models included):

```bash
docker run -i --rm -v /path/to/matter-folder:/docs:ro -e CATO_MCP_ROOT=/docs cato-api:local cato-mcp
```

## Recommended agent workflow

1. `list_documents` shows the files in the matter folder.
2. `read_document_protected("klage.txt")` returns the anonymized text with `PERSON_001`, `CASE_NUMBER_001`, ...
3. The agent works only with the placeholders.
4. If the result is `review` / `local_only` / `block`, the agent stops and asks the user.
5. A lawyer restores the original names in the final document via the admin API or `cato restore`, outside the agent.

## Conversations and prompts

With a conversation source (`CATO_SOURCE`) and/or a prompt store (`CATO_PROMPTS`) the server offers more tools. Setup and the guarantees behind them: [conversations.md](conversations.md), [prompts.md](prompts.md).

| Tool | Returns | Annotation |
|---|---|---|
| `list_conversations(since?, until?, tag?, limit?, cursor?)` | Opaque ids and metadata, no content | read-only |
| `get_conversation(conversation_id)` | Protected messages; withheld ones as `content: null`. Counts against the daily quota | read-only, not idempotent |
| `conversation_stats(since?, until?, group_by)` | Counts by day, tag, prompt, prompt_version, channel, language; groups < k suppressed | read-only |
| `list_prompts()`, `get_prompt(name, version?, label?)`, `prompt_history(name)`, `diff_prompt(name, from_version, to_version)` | Prompt versions and diffs | read-only |
| `create_prompt_draft(name, text? \| messages?, note?)` | New version without labels; rejected with customer data or placeholders | **write** |

Not available over MCP on purpose: moving a label (promotion), restore, and every argument that could change policy, destination or namespace.

## HTTP transport (remote MCP)

`CATO_MCP_HTTP=1` on the API serves the same tools at `/mcp` (streamable HTTP, stateless, JSON responses). Every request needs a Cato API key, `Authorization: Bearer <key>` or `X-API-Key`. The key decides the organization, the conversation quota and the actor in the audit log. Requests without a valid key get 401 before they reach the MCP server.

```bash
claude mcp add --transport http cato https://cato.internal.example/mcp \
  --header "Authorization: Bearer cato_..."
```

Cursor (`.cursor/mcp.json`):

```json
{ "mcpServers": { "cato": { "url": "https://cato.internal.example/mcp",
                            "headers": { "Authorization": "Bearer cato_..." } } } }
```

- Put TLS in front (reverse proxy), as for the rest of the API.
- `CATO_MCP_ALLOWED_HOSTS=cato.internal.example` enables DNS-rebinding protection for those hosts.
- One key per person: the quota and the audit log are per key.
- Claude Desktop and claude.ai custom connectors need OAuth; that is not included yet. Claude Code, Cursor and other clients that send a header work.

## Not included yet

- **Only plain text formats** for `read_document_protected`. PDF/DOCX go through `POST /v1/documents/protect`.
- **No OAuth** for remote MCP (see above).
- **Audit:** conversation reads and prompt changes are audited; `scan`/`anonymize` calls are not.
