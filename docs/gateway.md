# Privacy Gateway (OpenAI-compatible)

`POST /v1/chat/completions` is a drop-in endpoint for existing applications. Only the base URL and the key change:

```python
from openai import OpenAI

client = OpenAI(api_key="cato_...", base_url="http://localhost:8080/v1")
client.chat.completions.create(model="gpt-4o", messages=[
    {"role": "user", "content": "Fasse das Schreiben von Herrn Max Mustermann zusammen: ..."}])
```

The same works for LangChain (`ChatOpenAI(base_url=..., api_key=...)`), LlamaIndex (`OpenAILike`) and any client that speaks the OpenAI Chat Completions format.

## Flow

1. **Collect text:**
   - `messages[].content` (string or text parts)
   - `tool_calls[].function.arguments`

   Images and audio are rejected, because Cato cannot inspect them.
2. **Protect** every text with the active policy. A **per-request vault** keeps placeholders identical across all messages (`PERSON_001` in the system prompt = `PERSON_001` in the user message). It lives in memory only and is discarded after the request.
3. **Decide** (the most restrictive outcome across all messages wins):
   - `allow`: forwarded to the external provider.
   - `local_only`: forwarded to the **local model** (`CATO_LOCAL_UPSTREAM_URL`, e.g. Ollama) if one is configured. The policy is evaluated again for destination `local`. Without a local model: 403.
   - `review` / `block`: 403 with an OpenAI-style error (`type: cato_policy_violation`, `code: review|block|local_only`).
4. **Restore:** placeholders in the response (`content`, `tool_calls`) are replaced with the original values. The calling application sent those values itself. Placeholders the model invented stay unchanged and are counted in the trace.
5. **Trace:** the request is recorded with metadata only (see below). Every response carries the headers `X-Cato-Trace-Id` and `X-Cato-Outcome`.

The provider key (`CATO_UPSTREAM_KEY`) exists only on the server. Clients only know their Cato key.

## Configuration

| Variable | Meaning |
|---|---|
| `CATO_UPSTREAM_URL` | External provider, e.g. `https://api.openai.com/v1`, Azure OpenAI, an OpenAI-compatible proxy |
| `CATO_UPSTREAM_KEY` | Provider key (server-side only) |
| `CATO_UPSTREAM_PROVIDER` | Name for traces/metrics (`openai`, `azure`, ...) |
| `CATO_LOCAL_UPSTREAM_URL` | Optional local model (e.g. `http://ollama:11434/v1`) for `local_only` content |
| `CATO_LOCAL_MODEL` | Model name on the local upstream (e.g. `llama3.1`) |
| `CATO_GATEWAY_RESTORE` | `0` = return placeholders instead of original values |
| `CATO_GATEWAY_TIMEOUT` | Seconds (default 120) |

Anthropic, Bedrock and Vertex can be reached through an OpenAI-compatible proxy (e.g. LiteLLM) placed after Cato. Native endpoints for these providers are not included yet.

## Traces & metrics

| Endpoint | Content |
|---|---|
| `GET /v1/traces?limit=&outcome=&route=&since=` | Recent requests |
| `GET /v1/traces/{id}` | Decision history: request, detection, classification, policy, anonymization, provider, restore |
| `GET /v1/metrics?hours=24` | Requests, detection rate, anonymization rate, block rate, outcomes, providers, policies, entity distribution, latency (avg/p95), hourly time series |

**Traces contain no texts, values, placeholders or keys.** They hold only types, counts, risk, policy (`name@vN` + hash), outcome, provider, model, latency and status. A test checks this. Storage is SQLite (`CATO_TRACE_DB`), with retention via `CATO_TRACE_RETENTION_DAYS` (default 30).

## Limitations

- **No streaming yet** (`stream: true` → 400). Restoring across streamed chunks needs buffering at placeholder boundaries.
- **Each message is classified on its own.** Context from the system prompt (e.g. "criminal matter") does not affect the user message.
- **Text only.** Images and audio are rejected.
- **Only an OpenAI-compatible endpoint.** A native `/v1/messages` (Anthropic) does not exist yet.
