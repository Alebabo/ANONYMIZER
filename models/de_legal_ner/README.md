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
| German LER: precision / recall (persons, organisations, places) | 0.49 / 0.66 | **0.92 / 0.75** |
| German LER: persons, precision / recall | 0.61 / 0.74 | 0.91 / 0.84 |
| German LER: organisations, precision / recall | 0.32 / 0.40 | 0.88 / 0.54 |
| German LER: places, precision / recall | 0.51 / 0.84 | 0.97 / 0.86 |
| German LER: PER/ORG/LOC hits on courts, statutes, case law | 347 | **16** |
| Court decisions: inserted values found (859) | 0.988 | **0.995** |

Before the ORG work of 21.11.2026 (old rules, run 2): LER 0.92 / 0.71, organisations 0.88 / 0.45, persons
0.90 / 0.82, courts 0.992. Most of the organisation gain comes from the rules (companies with a hyphenated legal
form, "Firma X"); all variants: [docs/research/org-ner-results.md](../../docs/research/org-ner-results.md).

Details: `datasets/ler/eval_test*.json`, `datasets/courts/eval_test*.json`.

## Training

Run 3 (`training.json`, 21.11.2026): German LER train split (8,898 documents), the 2,874 LER documents with an
organisation twice more (`--org-repeat 2`), plus 3,891 paragraph blocks of local court decisions with synthetic
names, 6 epochs from `de_core_news_lg`, best epoch 6 on LER dev (NER-only dev F1 0.770 vs. 0.760 for run 2).

```bash
python packages/core/scripts/ner_train.py --ler datasets/ler --courts datasets/courts --synthetic 0 \
  --germeval 0 --epochs 6 --org-repeat 2 --out local/ner/models/de_legal_ner
```

Run 2 (same without `--org-repeat`) and run 1 (LER only) are described in the git history. `--org-augment N`
(copies of company documents with synthetic company names without legal form) did not help measurably; see
[docs/research/org-ner-results.md](../../docs/research/org-ner-results.md).

## Limits

- **Organisations are still the weak spot** (recall 0.54 on LER). What is left are mostly associations and
  public bodies by initialism ("ZDS", "MDK", "ver.di", "EU"), trademarks ("Widerspruchsmarke NIVONA") and
  companies named by a bare surname ("Arbeitsverhältnis mit Kraus"), which neither rules nor NER can tell from
  a person. Feedback from the Chat tab (`ner_train.py --feedback`) is the next lever.
- Measured on published court decisions. Pleadings, client letters and e-mails differ; measure on a real,
  local sample before production (see HANDOVER.md, evaluation).
