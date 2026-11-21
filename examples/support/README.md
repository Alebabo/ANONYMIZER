# Support example (synthetic)

Example detection patterns for support data. All formats are invented.

| File | Content |
|---|---|
| `patterns.yaml` | Example patterns for order numbers, customer numbers and ticket ids |

Start the API with these patterns (see [docs/detection.md](../../docs/detection.md)):

```bash
ANONYMIZER_CUSTOM_PATTERNS=examples/support/patterns.yaml \
ANONYMIZER_MCP_HTTP=1 ANONYMIZER_API_KEYS=anonymizer_demo_key_change_me_0123456789 anonymizer-api
```
