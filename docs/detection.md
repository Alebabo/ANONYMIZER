# Detection Engine

The engine lives in `packages/core/src/anonymizer/detect/`. It's deterministic: the same input and configuration always give the same output.

## Pipeline

1. **Language**: a stopword heuristic decides between `de`, `en` and `unknown`. With `unknown`, all recognizers run.
2. **Recognizers**: each recognizer produces candidates with a type, offsets, confidence and an optional checksum result (`validated`).
   - Rule-based recognizers always run.
   - spaCy NER runs by default (`de_core_news_lg`, `en_core_web_lg`). Its spans are cleaned up first: leading honorifics are cut off; spans across line breaks, role words and code fragments are dropped.
3. **Overlap resolution** (`resolve_overlaps`): when candidates overlap, a greedy pass keeps the best one. Losers go into `ScanResult.suppressed` with the id of the winner, so they stay auditable. Candidates are ranked by these criteria, in order:
   1. A valid checksum.
   2. Rule-based before statistical (NER never overrides a rule-based detection).
   3. How specific the type is.
   4. Span length.
   5. Confidence.
4. **Mention linking** (`propagate_mentions`): once a person has been found, further mentions of the full name or the surname are marked too.
   - Surnames are linked only if no other person in the document has the same surname.
5. **Refs** (`assign_refs`): mentions of the same person or organization get an opaque, document-local ref such as `person_1`, and roles are carried over. The ref is never derived from the raw value. This is the basis for consistent pseudonymization.
6. **Context signals**: cue words for the document context. Every detection carries the signals within ±150 characters. The window stops at blank lines (paragraphs).
   - Signal words inside detected values are ignored, e.g. "example" in `info@example.org`.
7. **Threshold**: detections below `min_confidence` (default 0.3) are not dropped. They are moved to `suppressed` with `reason=below_min_confidence`.

## Entity types

| Type | Category | Method |
|---|---|---|
| person | personal_data | Honorific or procedural role followed by a name; mention linking; optional spaCy |
| organization | personal_data | Name followed by a legal form (GmbH, AG, Inc., ...) |
| address | personal_data | Street with a street suffix + house number (+ postcode/city); US format |
| email, phone | personal_data | Regex; phone with a digit-count check |
| date, date_of_birth | personal_data | Calendar check; DOB only with a label (geb., born, DOB) |
| tax_id | personal_data | German Steuer-ID with ISO 7064 checksum |
| social_security_number | personal_data | DE pension insurance number, US SSN |
| iban | financial_data | mod-97 + country length; greedy matches are trimmed |
| bic, tax_number | financial_data | Only with a label |
| credit_card | financial_data | Luhn |
| money, vat_id | financial_data | Regex |
| case_number | legal_data | Court file numbers, prosecutor file numbers (Js), US dockets, labelled references |
| court, legal_citation | public_reference | Court names, § / Art. citations |
| health_data, biometric_data, special_category, criminal_record | special_category | Lexicons (Art. 9/10 GDPR) |
| privilege_marker | professional_secret | "Mandatsgeheimnis", "attorney-client privilege", ... |
| business_secret_marker | business_secret | "Geschäftsgeheimnis", "trade secret", "vertraulich", ... |

Names in chat self-introductions ("mein Name ist anna müller", "ich heiße …", "my name is …", "ich bin Lena Probe") are found by the `person_self_intro` recognizer. Strong cues also accept lowercase names; weak cues ("ich bin", "I am", "this is") need two capitalised tokens.

### Deployment patterns (`ANONYMIZER_CUSTOM_PATTERNS`)

House formats such as order numbers or customer ids are configured in a YAML file. The API, `anonymizer-mcp` and `anonymizer source-check` load it from `ANONYMIZER_CUSTOM_PATTERNS`; an invalid file stops the server, because a silently missing pattern would let identifiers through.

```yaml
patterns:
  - name: order_number            # entity type; pseudonymized by support-default
    pattern: '\b\d{4}-\d{4}\b'
    context_words: ['bestell', 'order']   # regex fragments shortly before the match raise confidence
    ignore_case: true
    confidence: 0.85
  - name: customer_number
    pattern: '\bKD-\d{6}\b'
    confidence: 0.95
```

Keys: `name` (snake_case), `pattern`, optional `entity_type`, `category`, `confidence` (0–1], `context_words`, `languages`, `ignore_case`. Example: [examples/support/patterns.yaml](../examples/support/patterns.yaml).

In code, custom types can be configured through `DetectorConfig.custom_entities`:

```python
Detector(DetectorConfig(custom_entities=[
    {"name": "client_number", "pattern": r"MDT-\d{6}", "category": "legal_data", "confidence": 0.9}
]))
```

## Context signals

| Signal | Meaning |
|---|---|
| client_relationship | Client relationship (Mandant, Mandat, our client) |
| criminal_proceeding | Criminal or investigation proceedings |
| litigation | Civil litigation |
| employment | Employment relationship, salary |
| financial_distress | Insolvency, enforcement |
| confidential | Confidentiality notice |
| example_context | Example, template, fictitious data |

Signals don't decide anything. The classification engine (step 2) combines them with the detections. Example from the spec:

- "Beispiel: Herr Max Mustermann ..." gives `example_context`.
- "Herr Max Mustermann ist unser Mandant im laufenden Strafverfahren" gives `client_relationship` and `criminal_proceeding`.

## Known limitations (rule-only mode)

- **Bare names without a cue** (no honorific, no role) are only found by spaCy NER. If the models are missing (`python -m spacy download de_core_news_lg en_core_web_lg`), the scan continues in rule-only mode and puts a warning in `ScanResult.warnings`. The API must surface this warning. Rule-only mode is not suitable for production.
- **NER is statistical.** It isn't deterministic in the sense of a fixed rule set, and legal jargon is outside its training domain. That's why NER only adds detections and never removes or reclassifies a rule-based one.
- **Capitalized German nouns after honorifics** ("Herr Ober") are recognized as names.
- **Addresses without a street suffix** ("Am Rosengarten 7a") are not recognized.
- **Lexicons are incomplete.** Adjective forms such as "schwerbehindert" are missing.
- **Ambiguous health terms** ("Therapie", "Reha") can cause false positives in non-medical contexts.

The limitations are tracked as `known_false_negatives` / `known_false_positives` in the test corpus. If one gets fixed, the test fails and the entry has to be moved to `expected`, so the documentation can't silently drift out of date.

## Evaluation

```bash
cd packages/core
anonymizer eval tests/corpus
```

Current state, on synthetic data only, with NER: 7 documents, 78 labelled entities, recall 0.97, 0 hits on `must_not_detect`. Without NER: recall 0.96. Entries marked `requires: ner` are skipped in rule-only mode. These numbers are **not** a statement about quality on real legal documents. A validation on real, anonymized documents is still outstanding.
