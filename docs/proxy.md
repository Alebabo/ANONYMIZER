# MCP proxy

`anonymizer-proxy` puts OpenAnonymizer in front of other MCP servers: databases, ticket systems, internal tools. The MCP client (Claude Code, Cursor, ...) sees one endpoint with the tools of every configured upstream. Every result is filtered before it reaches the model. Every call writes a trace and an audit entry.

```
Claude Code / Cursor
      │  MCP (stdio, or HTTP with a OpenAnonymizer key)
      ▼
OpenAnonymizer proxy ── detect → classify → policy → pseudonymize ── trace + audit (metadata only)
      ├── upstream "db"    (stdio: e.g. postgres-mcp, read-only)
      └── upstream "jira"  (HTTP)
```

## What it does

| Step | Behaviour |
|---|---|
| Tool list | Tools are prefixed with the upstream name (`db__execute_sql`). Tools annotated as write/destructive are hidden unless `allow_write: true` or listed in `tools.allow` |
| Arguments | Forwarded unchanged. Placeholders (`PERSON_001`) are **not** resolved: the upstream only knows real values |
| Text results | JSON (object/array) is protected value by value; keys stay readable. Other text is protected as a whole |
| Field names | Values under fields such as `email`, `vorname`, `nachname`, `telefon`, `iban`, `adresse`, `geburtsdatum` are treated as that entity even if detection finds nothing (`field_hints` adds more) |
| Known values | Values from those fields are also searched for in free text of later results from the same upstream (a surname from the customer table inside a ticket) |
| Numbers | JSON numbers under hinted fields are protected. Other integers with 12 or more digits are checked by the rules (card numbers); shorter numbers pass |
| Identifiers | Single lower-case identifiers (`telefon`, `status`, `open`) only go through rules, not NER, to avoid over-redaction of column names |
| Policy | Values the policy does not allow for the destination become `[WITHHELD]` (JSON) or a notice (text) |
| Non-text content | Images, audio, binary resources and resource links are withheld |
| Consistency | Same value → same placeholder per upstream for the lifetime of the process, or across restarts with `ANONYMIZER_VAULT_KEY` |
| Errors | Upstream errors and filter errors return a generic error. The unfiltered result is never returned (fail closed) |

## Modes

- `enforce` (default): the model only sees the filtered result.
- `observe`: the model sees the **original** result. OpenAnonymizer only records what it would have protected. Use it **only with synthetic or test data**, or with approval for the system in question. The dashboard shows a warning while an upstream runs in observe mode.

## Configuration

`anonymizer-proxy.yaml` (example: [examples/proxy/anonymizer-proxy.yaml](../examples/proxy/anonymizer-proxy.yaml)):

```yaml
destination: external          # what sits behind the MCP client: external (cloud model) or local
policy: support-default        # default policy; built-in name or path to a policy YAML
custom_patterns: patterns.yaml # optional, like ANONYMIZER_CUSTOM_PATTERNS
trace_db: /data/traces.db      # stdio only: the API's trace file, so calls show up in the dashboard
audit_db: /data/audit.db       # stdio only
upstreams:
  db:
    command: ["postgres-mcp", "--access-mode=restricted"]
    env: { DATABASE_URI: "${REPLICA_URI}" }   # ${VAR} comes from the environment
    mode: enforce
    tools: { allow: ["execute_sql", "list_schemas", "list_objects", "get_object_details"] }
    field_hints: { name: person }             # "name" means a person in this system
  jira:
    url: https://jira-mcp.internal/mcp
    headers: { Authorization: "Bearer ${JIRA_TOKEN}" }
    mode: observe
    timeout: 30
```

| Key | Meaning |
|---|---|
| `command` / `url` | Exactly one: stdio subprocess or streamable HTTP endpoint |
| `env`, `cwd`, `headers` | Passed to the subprocess / sent to the HTTP upstream |
| `mode` | `enforce` or `observe` |
| `policy`, `language` | Per upstream; default from the top level / auto-detected |
| `tools.allow`, `tools.deny` | Exact tool names. With `allow`, only those tools exist |
| `allow_write` | Also expose tools annotated as not read-only or destructive (unannotated tools are exposed) |
| `field_hints` | Extra field name → entity type (`person`, `email`, `phone`, `iban`, `address`, ...) |
| `timeout` | Seconds per call (default 60) |

Upstream names: lower case letters, digits, `_`, max. 24 characters.

## Run it

### stdio (simplest; one per person)

```bash
anonymizer-proxy --config anonymizer-proxy.yaml --check        # connect, print upstreams and tools, exit
claude mcp add anonymizer-proxy -- anonymizer-proxy --config /abs/path/anonymizer-proxy.yaml
```

Point `trace_db` and `audit_db` (or `ANONYMIZER_TRACE_DB` / `ANONYMIZER_AUDIT_DB`) at the files of a running OpenAnonymizer API to see the calls in its dashboard. The proxy writes into the `default` organization (`org:` in the file changes it).

### HTTP inside the API (shared; keys and quotas per person)

```bash
ANONYMIZER_PROXY_CONFIG=/config/anonymizer-proxy.yaml anonymizer-api
claude mcp add --transport http anonymizer-proxy https://anonymizer.internal.example/proxy/mcp \
  --header "Authorization: Bearer anonymizer_..."
```

- Every request needs a OpenAnonymizer API key (401 otherwise). The key is the actor in the audit log.
- `GET /v1/proxy` shows upstream status, mode, policy and tool counts.
- Upstream subprocesses run inside the API container. With docker compose, mount the config and make the upstream's command available in the image.

## Dashboard

- **MCP Proxy** (`/proxy`): upstream status, entity types found, calls per tool, and the field paths where personal data was found (`$.email`, `$.rows[].notiz`, ...).
- **Traces** with the filter "MCP proxy": one trace per call with upstream, tool, mode, policy outcome, entity types per field and latency.

Traces never contain values, placeholders or results. To check what the model actually received, look at the client side (the agent's transcript), not at OpenAnonymizer.

## Limits

- **Free SQL** can still extract information through aggregation or `LIKE` probes. Use a read-only user on a replica and prefer an allow list of tools.
- **Recall is not 100 %.** Unusual names in free text can slip through NER. Field hints and known values reduce this for structured data. Measure on a real sample before using `enforce` on production data (see [plan.md](../plan.md) section 4).
- **Different spellings** of the same value (`+49 170 …` vs. `0170 …`) get different placeholders.
- **The client can bypass OpenAnonymizer** if it has a direct MCP connection to the same system. Only network rules prevent that.
- **Phone numbers stored as JSON numbers** under a field name that is not a hint are not recognised. Add the field to `field_hints`.
- Resources and prompts of upstreams are not proxied yet, only tools.
