# Support example (synthetic)

Synthetic data for trying conversation access and prompt management without any real customer data.
All names, numbers and addresses are invented.

| File | Content |
|---|---|
| `conversations.jsonl` | 24 support chats over 4 days, two prompt versions (`support-bot@11`, `@12`) |
| `patterns.yaml` | Example patterns for order numbers, customer numbers and ticket ids |

Start the API with these files (see [docs/conversations.md](../../docs/conversations.md)):

```bash
ANONYMIZER_SOURCE=jsonl ANONYMIZER_SOURCE_PATH=examples/support/conversations.jsonl \
ANONYMIZER_CUSTOM_PATTERNS=examples/support/patterns.yaml ANONYMIZER_PROMPTS=local \
ANONYMIZER_MCP_HTTP=1 ANONYMIZER_API_KEYS=anonymizer_demo_key_change_me_0123456789 anonymizer-api
```
