# de_legal_ner: German NER for legal texts

NER weights for spaCy `de_core_news_lg` (3.8), fine-tuned on court decisions. Only the `ner` component is
stored (about 6 MB, Git LFS); vectors, tagger etc. come from the base model
(`python -m spacy download de_core_news_lg`).

```bash
ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_legal_ner/ner"
```

Training data and measurement: [datasets/ler](../../datasets/ler/README.md),
[datasets/courts](../../datasets/courts/README.md); `training.json` holds the run.

## Results (test splits, full pipeline: rules + NER, 21.11.2026)

| | `de_core_news_lg` | `de_legal_ner` |
|---|---|---|
| German LER: precision / recall (persons, organisations, places) | 0.48 / 0.63 | **0.92 / 0.71** |
| German LER: persons, precision / recall | 0.60 / 0.74 | 0.90 / 0.82 |
| German LER: organisations, precision / recall | 0.26 / 0.30 | 0.88 / 0.45 |
| German LER: places, precision / recall | 0.51 / 0.84 | 0.97 / 0.85 |
| German LER: PER/ORG/LOC hits on courts, statutes, case law | 348 | **16** |
| Court decisions: inserted values found (859) | 0.987 | **0.992** |

Details: `datasets/ler/eval_test*.json`, `datasets/courts/eval_test*.json`.

## Training

Run 2 of 2 (`training.json`): German LER train split (8,898 documents) plus 3,891 paragraph blocks of local
court decisions with synthetic names, 6 epochs from `de_core_news_lg`, best epoch 4 on LER dev. Run 1 (LER
only) scored the same within noise (LER test F1 0.807 vs. 0.803); run 2 was kept for its higher person recall
and the wider name pool (names of many origins common in Germany).

```bash
python packages/core/scripts/ner_train.py --ler datasets/ler --courts datasets/courts --synthetic 0 \
  --germeval 0 --epochs 6 --out local/ner/models/de_legal_ner
```

## Limits

- **Organisations are the weak spot** (recall 0.45 on LER): company names without a legal form ("Haas",
  "VCS") are often missed. Feedback from the Chat tab (`ner_train.py --feedback`) is the next lever.
- Measured on published court decisions. Pleadings, client letters and e-mails differ; measure on a real,
  local sample before production (see HANDOVER.md, evaluation).
