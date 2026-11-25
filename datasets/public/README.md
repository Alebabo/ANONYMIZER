# Public German texts with labelled personal data

German parts of four public datasets, converted to one format (`<source>/{train,test}.jsonl.gz`, one
`{id, text, entities: [{start, end, label}]}` per line). Used to measure the detector and as NER training data:

```bash
python packages/core/scripts/public_pii.py download     # rebuild the files from Hugging Face (same bytes)
python packages/core/scripts/public_pii.py eval         # all sources; --source smartdata|mapa|e3jsi|urchade
python packages/core/scripts/ner_train.py ... --public datasets/public [--public-limit N]
```

| Source | Licence | Content | German docs train / test |
|---|---|---|---|
| [DFKI-SLT/smartdata-corpus](https://huggingface.co/datasets/DFKI-SLT/smartdata-corpus) | CC BY 4.0 | News, tweets, traffic reports; companies (`ORGANIZATION_COMPANY`) are their own type | 1,861 / 230 |
| [joelniklaus/mapa](https://huggingface.co/datasets/joelniklaus/mapa) (MAPA project) | CC BY 4.0 | EUR-Lex judgments and opinions annotated for anonymisation, one sentence per doc | 1,457 / 558 |
| [E3-JSI/synthetic-multi-pii-ner-v1](https://huggingface.co/datasets/E3-JSI/synthetic-multi-pii-ner-v1) | MIT | Synthetic texts: banking, finance, health, legal, general | 333 / 99 |
| [urchade/synthetic-pii-ner-mistral-v1](https://huggingface.co/datasets/urchade/synthetic-pii-ner-mistral-v1) | Apache-2.0 | Synthetic texts with many identifiers; German ones picked by function words | 2,644 / 671 |

| [naeyn/nobody-pii-synth-de](https://huggingface.co/datasets/naeyn/nobody-pii-synth-de) | Apache-2.0 | Template texts with Faker values (mails, tickets, chats, letters, contracts); companies include bare surnames | 5,649 / 296 |
| [Wismut/nym-pii-multilingual-data](https://huggingface.co/datasets/Wismut/nym-pii-multilingual-data) | MIT | Synthetic support, IT and finance texts, ~20 % with OCR noise; German rows by function words, without documents holding keys or passwords | 24,995 / 1,305 |
| [masterofaudio2077/medical-pii-multilingual](https://huggingface.co/datasets/masterofaudio2077/medical-pii-multilingual) | Apache-2.0 | LLM-written German letters, forms, reports over a generated fact sheet; hospitals are `public_body` | 2,228 / 543 |

E3-JSI, urchade and medical have no test split upstream: every fifth document (by text hash) is held out.
nym labels companies only sometimes: in NER training, unlabelled names with a legal form ("RideSharePlus AG") are
left out of the loss instead of being taught as O.

Searched on Hugging Face (25.11.2026) and not used: ai4privacy openpii-1m/1.5m and their CC BY 4.0 "mini" subsets
(own licence upstream), abubasith86/pii-dataset-de-v1 (licence "other", mostly ai4privacy rows), Babelscape
multinerd/wikineural (CC BY-NC-SA), nvidia/Nemotron-PII and gravitee-io/pii-detection-dataset (English only),
betterdataai/gliner-multilingual-ner-silver-v1 (LLM silver labels, "high recall, some noise expected"),
tudarmstadt-lt/germaner (GermEval 2014, already used).
Not used: ai4privacy/open-pii-masking-500k (Llama Community License, commercial use needs written permission).

## Conversion

- Labels are mapped to OpenAnonymizer types (`person`, `organization`, `location`, `address`, `date`, `email`, …,
  `LABELS` in `public_pii.py`). Labels without personal data (professions, diseases, traffic triggers, numbers)
  are dropped.
- Courts, authorities, EU institutions, hospitals and SmartData's plain `ORGANIZATION` become `public_body`:
  measured (masked only), never taught as ORG, as in LER. urchade's `organization` is also `public_body`, because
  it mixes companies and institutions.
- Person spans lose a leading salutation or title ("Frau Dr. Anna Müller" → "Anna Müller"); MAPA titles, roles
  and nationalities are not part of a person.
- Tokenized sources are detokenized ("15 . Mai" → "15. Mai", "max . muster @ web . de" → "max.muster@web.de"),
  otherwise dates, e-mails and phone numbers could not be found. A hyphen or slash is joined only before a
  lower-case word or a digit ("123-45", "Schmidt-mueller"), so "Berlin - Hamburg" and "Commerzbank - Konto" stay split.
- NER training (`--public`): `person` → PER, `organization` → ORG, `location` → LOC; `public_body` and `address`
  are left out of the loss; everything else is O. Overlapping spans: the longer one wins.

SmartData's `LOCATION_STREET` includes road names ("A8", "B217"), counted as `address`.

## Results (24.11.2026, `de_core_news_lg` with the default detector; `eval.json` holds every label)

| | Masked recall | Precision (lower bound) | Persons | Companies | Locations | Dates |
|---|---|---|---|---|---|---|
| smartdata (news) | 0.587 | 0.702 | 0.91 | **0.50** | 0.73 | 0.24 |
| mapa (EUR-Lex) | 0.591 | 0.451 | 0.87 | – | – | 0.87 |
| e3jsi (synthetic) | 0.938 | 0.733 | 0.97 | 0.81 | 0.96 | 0.97 |
| urchade (synthetic) | 0.911 | 0.622 | 0.96 | (0.77) | 0.91 | 1.00 |

Companies in real news text are found half the time, which matches the company recall on LER (0.54). Public bodies
are masked in 24 % (MAPA) to 71 % (urchade) of cases; for legal texts that is wanted, since courts stay visible.
Precision is a lower bound: the gold sets do not label everything (amounts, public companies in MAPA).
