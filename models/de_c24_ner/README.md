# de_c24_ner: fine-tuned German NER for support mails, chats and letters

NER weights for spaCy `de_core_news_lg` (3.8), fine-tuned on bank support text. Only the `ner` component is
stored here (about 6 MB). Word vectors, tagger and the other components come from the base model, which must be
installed (`python -m spacy download de_core_news_lg`).

Version: v6 (20.11.2026), trained from `de_core_news_lg`, best of 6 epochs on the dev split (epoch 1).

## Use

```bash
ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_c24_ner/ner"
```

The path is relative to the working directory of the process. Without the variable the anonymizer uses the
plain `de_core_news_lg`. With this model the pipeline also keeps lower-case chat entities ("schepers", "axa"),
which the stock model gets wrong too often.

## Training

Only the `ner` component is trained; it has its own tok2vec, so tagger and parser stay as shipped. Training
continues from the original weights (Adam, dropout 0.25, batch size 8 to 32, seed 24). Per epoch:

| Source | Examples | Labels |
| --- | --- | --- |
| GermEval 2014 NER (public, CC BY 4.0) | 6,000 sentences | complete; OTH as MISC |
| MultiCoNER v2, German (public, CC BY 4.0) | 4,000 lower-case sentences | persons, groups and places mapped to PER/ORG/LOC; facilities left out of the loss |
| Synthetic support texts from templates | 4,000 (one in five without entities) | complete |
| Gold train split: sbx/int mails, chats and test runs | 430, repeated 3 times | complete, reviewed |
| OCR letters from the service tool (sbx/int) | 340, repeated 2 times | partial: confirmed entities and confirmed non-entities only |

Names, organisations and places used in the synthetic texts never occur in the dev or test split. Address spans,
and entities that do not line up with spaCy tokens, are left out of the loss.

Scripts: `packages/core/scripts/ner_train.py` (training) and `packages/core/scripts/ner_gold.py` (gold set and
evaluation). The annotated data is not part of this repository.

## Results

Scores are from the anonymizer pipeline (NER plus the rules in `detect/ner.py` and `detect/orgs.py`), with an
exact match of start, end and label required. F1 over PER, ORG and LOC unless stated.

| Model | Test split (955 docs) | Handwritten holdout (99 docs) | syntriq, persons only (2,957) |
| --- | --- | --- | --- |
| `de_core_news_lg` + rules | – | 0.80 | 0.85 |
| v4 + rules | 0.920 | 0.861 | 0.927 |
| **v6 + rules** | **0.939** | **0.900** | **0.934** |

- The handwritten holdout is the most honest number: fictional mails, chats, letters and bot answers written as
  a clean test set, with names, firms and places that occur neither in training nor in the organisation list.
  It was never used to tune rules or select models.
- The test split repeats signatures and test customers, and the rules were tuned on the dev split (0.965), so
  its score is higher than on fresh text.
- [syntriq/german-pii-benchmark](https://huggingface.co/datasets/syntriq/german-pii-benchmark) (Apache-2.0)
  labels persons only; scored with `packages/core/scripts/ner_external.py`.

Per label on the holdout (v6): PER F1 0.94, ORG 0.81, LOC 0.94. Remaining errors are mostly small firms without
a legal form ("Weserkurier", "Etsy"), names with hyphens, initials or particles, and single first names in lists.
A v7 with more synthetic name shapes scored higher on dev (0.975) but lower on test, holdout and syntriq, so it
was not shipped.

## Note on privacy

The training data includes texts and scanned letters from internal test stages. They contain names of employees
and test customers, and some letters may be copies of real mail with names of third parties. A NER model does not
store its training texts, but it can be biased towards names it has seen.
