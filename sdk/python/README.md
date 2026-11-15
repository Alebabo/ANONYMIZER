# cato-sdk

Python client for the [Cato](../../README.md) privacy API.

```bash
pip install cato-sdk            # plus "cato-sdk[openai]" for the gateway helper
```

```python
from cato_sdk import Cato

cato = Cato(api_key="cato_...", base_url="http://localhost:8080")   # or CATO_API_KEY / CATO_BASE_URL

result = cato.protect("Max Mustermann ist unser Mandant ...")
if result.allowed:
    print(result.text)          # "PERSON_001 ist unser Mandant ..."
else:
    print(result.outcome, result.decision.reasons)

cato.anonymize("Herr Max Mustermann", methods={"person": "redact"}).text
cato.protect_document("klage.docx").content      # anonymized DOCX bytes
cato.scan("...").detections                      # types and offsets, never raw values

# Existing OpenAI code through the privacy gateway:
client = cato.openai()
client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "..."}])
```

`protect(..., require_allowed=True)` raises `PolicyViolation` instead of returning `text=None`.

The import name is `cato_sdk` (not `cato`) so it does not clash with the server-side engine package `cato-core`.
