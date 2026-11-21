# German LER: gold data for legal texts

Court decisions of seven federal courts (2017/2018) from the German LER dataset (CC BY 4.0, see
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)), converted to the gold format of
`anonymizer.ner_dataset` by `packages/core/scripts/ler_data.py build`.

| File | Docs | Persons | Organisations | Places |
|---|---|---|---|---|
| `ler_train.jsonl.gz` | 8,898 | 2,859 | 2,092 | 1,585 |
| `ler_dev.jsonl.gz` | 1,111 | 348 | 273 | 188 |
| `ler_test.jsonl.gz` | 1,113 | 324 | 253 | 235 |

A document is six consecutive sentences. Every line: `key`, `split`, `text`, `spans` (`start`, `end`, `label`, `text`).

## Labels

| Label | Meaning | Use |
|---|---|---|
| `PER`, `ORG`, `LOC` | Private persons (also judges, lawyers), companies and other organisations, places | NER entities, scored |
| `ADDR` | Streets | Address recognizer; NER predictions on them are not scored |
| `GRT`, `INN` | Courts, public institutions | Public: the court rule must find courts; PER/ORG/LOC on them is a false positive |
| `RS`, `GS`, `LIT`, `VO`, `EUN`, `VS`, `VT` | Case law, statutes, literature, ordinances, EU norms, regulations, contracts | Public references: rules should find them; PER/ORG/LOC on them is a false positive |

The published decisions are already anonymized ("Rechtsanwalt F", "die P GmbH", "in B."). Those values were
replaced by synthetic names, companies and cities. Train and dev/test use disjoint name lists, so scores measure
generalisation, not memory.

## Measure

```bash
python packages/core/scripts/ler_data.py eval --split dev     # or --split test; --no-ner for rules only
```

Runs the full detector (rules + spaCy `de_core_news_lg`) and writes `eval_<split>.json` (committed as the
baseline) and `errors_<split>.md` (not committed).

Results on the test split (full detector; `eval_test.json` = plain `de_core_news_lg` with the rules of
21.11.2026 including the organisation rules, `eval_test_de_legal_ner.json` = with the fine-tuned model, run 3):

| | Rules before 21.11. | Rules now | Rules now + `de_legal_ner` |
|---|---|---|---|
| Persons/organisations/places: precision / recall | 0.32 / 0.63 | 0.49 / 0.66 | **0.92 / 0.75** |
| Organisations: precision / recall | | 0.32 / 0.40 | 0.88 / 0.54 |
| Courts found | 0.69 | 0.97 | 0.97 |
| Statute citations found | 0.38 | 0.92 | 0.92 |
| Case-law references found | 0.74 | 0.96 | 0.96 |
| Case numbers in case law found | 0.81 | 1.00 | 1.00 |
| PER/ORG/LOC on public references (false positives) | 773 | 347 | **16** |

## Train

```bash
python -m spacy download de_core_news_lg
python packages/core/scripts/ner_train.py --ler datasets/ler --synthetic 0 --germeval 0 \
  --out local/ner/models/de_legal_ner --epochs 8
```

Without `local/ner/gold.jsonl` the LER dev split selects the best epoch. Adopt a model only if LER test improves
and, where available, the support gold set does not get worse.

## Rebuild

The original CoNLL files are in `raw/` (gzipped, CC BY 4.0), so no download is needed:

```bash
python packages/core/scripts/ler_data.py build       # reads local/ler if present, else raw/
python packages/core/scripts/ler_data.py download    # optional: fresh copy to local/ler
```
