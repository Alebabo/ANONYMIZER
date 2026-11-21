---
language:
  - de
license: apache-2.0
task_categories:
  - token-classification
tags:
  - pii
  - benchmark
  - anonymization
  - presidio
  - gdpr
  - synthetic
  - german
pretty_name: German PII Benchmark
size_categories:
  - n<1K
configs:
  - config_name: default
    data_files:
      - split: test
        path: test.jsonl
---

# German PII Benchmark

**Deutsch:** 687 deutsche Dokumente mit exakt annotierten personenbezogenen Daten in 19 Kategorien, darunter alle deutschen Kennnummern. Zum Vergleich von PII-Erkennern und Anonymisierungs-Pipelines wie Microsoft Presidio. Alle Daten sind erfunden.

A benchmark for detecting personal data in German text. 687 documents of 26 types, 8,035 labelled spans in 19 categories that use Microsoft Presidio's entity names. Presidio's documentation states that its German recognizers have not been evaluated on labelled German data. This set makes that measurable, for Presidio and for any PII model.

Code, evaluation script and demo source: [github.com/Syntriq-GmbH/tarn](https://github.com/Syntriq-GmbH/tarn).

## Leaderboard

| Model | Masked recall | Masked precision | Strict F1 |
|---|---|---|---|
| syntriq/tarn-german-pii-large | 0.999 | 0.995 | 0.992 |
| syntriq/tarn-german-pii-base | 0.999 | 0.993 | 0.989 |
| syntriq/tarn-german-pii-gliner-base | 0.997 | 0.997 | 0.991 |
| bardsai/eu-pii-anonimization-multilang | 0.978 | 0.772 | 0.677 |
| urchade/gliner_multi_pii-v1 | 0.892 | 0.875 | 0.687 |
| openai/privacy-filter | 0.887 | 0.671 | 0.462 |
| tabularisai/eu-pii-safeguard | 0.788 | 0.892 | 0.539 |
| Presidio 2.2.366, German recognizers only | 0.348 | 0.970 | 0.474 |

![Benchmark comparison](https://huggingface.co/datasets/syntriq/german-pii-benchmark/resolve/main/assets/benchmark.png)

The Syntriq models were trained on data from the same value generators, which gives them a home advantage on this set.

Masked recall is the share of gold spans that any prediction overlaps, regardless of label: the share of personal data that would be masked. Masked precision is the share of predictions that overlap a gold span. Strict F1 requires the exact span and label.

## Contents

| Field | Meaning |
|---|---|
| `id` | Document id |
| `document` | Document type, e.g. Lohnabrechnung, Schufa-Selbstauskunft, Slack-Verlauf |
| `style` | Writing style, e.g. formal, OCR output, Austrian or Swiss usage |
| `text` | The document |
| `entities` | `start` and `end` character offsets, `label`, `text` |

Labels: PERSON, EMAIL_ADDRESS, PHONE_NUMBER, ADDRESS, DATE_OF_BIRTH, IBAN_CODE, CREDIT_CARD, IP_ADDRESS, CUSTOMER_ID, DE_TAX_ID, DE_TAX_NUMBER, DE_SOCIAL_SECURITY, DE_HEALTH_INSURANCE, DE_ID_CARD, DE_PASSPORT, DE_FUEHRERSCHEIN, DE_KFZ, DE_LANR, DE_BSNR.

| Label | Spans |
|---|---|
| PERSON | 2957 |
| ADDRESS | 1063 |
| EMAIL_ADDRESS | 961 |
| PHONE_NUMBER | 837 |
| CUSTOMER_ID | 469 |
| DATE_OF_BIRTH | 448 |
| IBAN_CODE | 262 |
| IP_ADDRESS | 166 |
| DE_TAX_ID | 141 |
| DE_ID_CARD | 110 |
| CREDIT_CARD | 103 |
| DE_KFZ | 97 |
| DE_HEALTH_INSURANCE | 80 |
| DE_TAX_NUMBER | 76 |
| DE_FUEHRERSCHEIN | 66 |
| DE_PASSPORT | 61 |
| DE_LANR | 51 |
| DE_SOCIAL_SECURITY | 49 |
| DE_BSNR | 38 |

## How it was built

- Kimi K3.1 Pro wrote document templates with placeholders for 26 document types that do not occur in the Syntriq training data, for example Lohnabrechnung, Patientenverfügung, Heil- und Kostenplan, CSV exports and team chats.
- Values were filled in with Faker and with generators that follow the official formats and check digits: Steuer-ID (ISO 7064), Steuernummer (ELSTER), Rentenversicherungsnummer, Krankenversichertennummer, ICAO document numbers, Führerschein (FeV Anlage 8), LANR, BSNR, IBAN, Luhn-valid card numbers.
- Names and street names come from a pool that is disjoint from the training data.
- Templates with leftover placeholders, invented names or unlabeled contact data were rejected automatically, every document was then checked by an LLM audit and every flagged document by hand.
- No real personal data was used. Every value is invented, every identifier is checksum-valid but randomly generated.

## Evaluate

```python
from datasets import load_dataset

documents = load_dataset("syntriq/german-pii-benchmark", split="test")
```

The scoring code (strict, overlap and masked metrics) is `score` in `german-pii/model.py` of the Syntriq Labs repository.

## Limitations

- Synthetic documents written by one LLM. Real documents are messier, so absolute scores on real data will be lower.
- The rarer German identifiers have only a few dozen spans each, compare them with confidence intervals in mind.
- Austrian and Swiss national identifiers are not included.

## License and citation

Apache-2.0.

```bibtex
@misc{syntriq2026germanpiibenchmark,
  title  = {German PII Benchmark},
  author = {Syntriq Labs},
  year   = {2026},
  url    = {https://huggingface.co/datasets/syntriq/german-pii-benchmark}
}
```
