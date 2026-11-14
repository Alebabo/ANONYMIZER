# cato-core

Privacy engine for legal AI: detection, classification, anonymization, policies.
Status: step 1 (detection) is implemented.

```bash
pip install -e ".[dev]"          # optional: ".[ner]" for spaCy
pytest
cato scan document.txt           # JSON without raw values
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

Details: [docs/detection.md](../../docs/detection.md)
