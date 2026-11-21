# German financial and banking texts with labelled personal data

Three synthetic, Apache-2.0 datasets from Hugging Face, copied unchanged into `raw/` (license texts and cards
next to the data). Used to measure the detector on bank, finance and support documents:

```bash
python packages/core/scripts/finance_data.py download        # Gretel files (see below), once
python packages/core/scripts/finance_data.py eval            # all sources; --source gretel|syntriq|easyoctopus
```

| Source | Content | Used |
|---|---|---|
| [gretelai/synthetic_pii_finance_multilingual](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) | Finance documents (MT940, BAI, ISDA, statements, loan and insurance papers, support logs); German part 4,077 train / 453 test | German test split (`raw/gretel/German_*.parquet`, **not committed**: its synthetic API keys and tokens trip GitHub push protection; fetched by `download`) |
| [syntriq/german-pii-benchmark](https://huggingface.co/datasets/syntriq/german-pii-benchmark) | 687 German documents of 26 types (Schufa, Lohnabrechnung, …), check-digit-valid IBAN, tax ids, social security numbers | all (`raw/syntriq/test.jsonl.gz`) |
| [EasyOctopus/german-support-pii-data](https://huggingface.co/datasets/EasyOctopus/german-support-pii-data) | Short German support messages with IBAN, BIC, cards, customer/order/account ids | test split (`raw/easyoctopus/*.jsonl.gz`) |

Not used: ai4privacy/pii-masking-* (commercial use only with a separate license), Isotonic/pii-masking-200k
(CC BY-NC).

## Metrics

- **masked**: share of gold values that any detection overlaps (would be hidden). The number that matters for
  data protection.
- **typed**: share found with the matching OpenAnonymizer type.
- **precision (lower bound)**: share of detections that overlap a gold value. The gold sets do not label
  everything (e.g. amounts, public companies), so true precision is higher.

## Results (21.11.2026, plain `de_core_news_lg`; `eval.json` holds every label)

| | Before | After the rule update |
|---|---|---|
| syntriq: masked recall / precision | 0.808 / 0.523 | **0.905 / 0.551** |
| easyoctopus: masked recall / precision | 0.398 / 0.618 | **0.586 / 0.702** |
| gretel: masked recall / precision | 0.636 / 0.367 | **0.654 / 0.372** |
| Phone numbers (syntriq) | 0.789 | 0.989 |
| IP addresses (syntriq) | 0.006 | 1.000 |
| ID card / passport / driving licence (syntriq) | 0.01 / 0.07 / 0.00 | 0.72 / 0.75 / 0.59 |
| Tax number (syntriq) | 0.329 | 0.776 |
| Customer ids (syntriq) | 0.041 | 0.382 |

Rule update: phone numbers with bracketed area codes and two-digit groups; identifiers after a label
(Kundennummer, Personalausweis, Reisepass, Führerschein, Krankenversichertennummer, Kennzeichen, Steuernummer,
BIC/Bankcode) with new types `customer_number`, `id_document`, `health_insurance_number`, `license_plate`;
IPv4/IPv6 (`ip_address`). No change on the legal test splits (German LER, court decisions).

## Open gaps

- Unlabelled ids in running text (customer and order numbers without "Kundennummer:") – company formats belong in
  custom patterns (`ANONYMIZER_CUSTOM_PATTERNS`, see examples/support/patterns.yaml).
- EasyOctopus uses deliberately invalid IBANs and BICs ("DE00 0000 …", "TESTDEB…"). Without a label such values
  are dropped by the checksum; a labelled invalid IBAN is kept and flagged (`validated=False`).
- Gretel contains leftover placeholders ("[Unternehmenname]") and English structured formats (CSV, FIX, XBRL);
  its recall is a rough indicator only.
