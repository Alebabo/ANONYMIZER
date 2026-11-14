# cato-core

Privacy engine for legal AI: detection, classification, anonymization, policies.
Status: Phase 1 complete (detection, classification, anonymization + vault, policies, REST API, Docker).

```bash
pip install -e ".[dev]"
python -m spacy download de_core_news_lg
python -m spacy download en_core_web_lg
pytest
cato scan document.txt           # detections as JSON, no raw values
cato classify document.txt       # risk per entity and document
cato anonymize document.txt      # transformed text (add --vault/--namespace for reversible)
cato protect document.txt        # full pipeline with the built-in legal-default policy
CATO_API_KEYS=... cato-api       # REST API on 127.0.0.1:8080 (see docs/API.md)
cato eval tests/corpus           # recall / false positives on the corpus
```

```python
from cato import scan

result = scan("Herr Max Mustermann ist unser Mandant im Strafverfahren 123 Js 4567/24.")
for d in result.detections:
    print(d.entity_type, d.confidence, d.attributes, d.signals)
```

`Detection.text` contains the raw value. For logs and traces use only
`Detection.redacted()`.

Details: [docs/detection.md](../../docs/detection.md), [docs/classification.md](../../docs/classification.md), [docs/anonymization.md](../../docs/anonymization.md), [docs/policies.md](../../docs/policies.md)
