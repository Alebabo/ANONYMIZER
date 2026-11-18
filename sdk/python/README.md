# anonymizer-sdk

Python client for the [OpenAnonymizer](../../README.md) privacy API.

```bash
pip install anonymizer-sdk            # plus "anonymizer-sdk[openai]" for the gateway helper
```

```python
from anonymizer_sdk import OpenAnonymizer

anonymizer = OpenAnonymizer(api_key="anonymizer_...", base_url="http://localhost:8080")   # or ANONYMIZER_API_KEY / ANONYMIZER_BASE_URL

result = anonymizer.protect("Max Mustermann ist unser Mandant ...")
if result.allowed:
    print(result.text)          # "PERSON_001 ist unser Mandant ..."
else:
    print(result.outcome, result.decision.reasons)

anonymizer.anonymize("Herr Max Mustermann", methods={"person": "redact"}).text
anonymizer.protect_document("klage.docx").content      # anonymized DOCX bytes
anonymizer.scan("...").detections                      # types and offsets, never raw values

# Existing OpenAI code through the privacy gateway:
client = anonymizer.openai()
client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "..."}])
```

`protect(..., require_allowed=True)` raises `PolicyViolation` instead of returning `text=None`.

The import name is `anonymizer_sdk` (not `anonymizer`) so it does not clash with the server-side engine package `anonymizer-core`.
