# de_custom_ner: fine-tuned German NER for support mails, chats and letters

NER weights for spaCy `de_core_news_lg` (3.8), fine-tuned on bank support text. Only the `ner` component is
stored here (about 6 MB). Word vectors, tagger and the other components come from the base model, which must be
installed (`python -m spacy download de_core_news_lg`).

Version: v4 (20.11.2026), best of 6 epochs on the dev split.

## Use

```bash
ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_custom_ner/ner"
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
| Synthetic support texts from templates | 4,000 (one in five without entities) | complete |
| Gold train split: sbx/int mails, chats and test runs | 393, repeated 3 times | complete, reviewed |
| OCR letters from the service tool (sbx/int) | 340, repeated 2 times | partial: confirmed entities and confirmed non-entities only |

Names, organisations and places used in the synthetic texts never occur in the dev or test split. Address spans,
and entities that do not line up with spaCy tokens, are left out of the loss.

Scripts: `packages/core/scripts/ner_train.py` (training) and `packages/core/scripts/ner_gold.py` (gold set and
evaluation). The annotated data is not part of this repository.

## Results

Held-out test split: 776 documents, 315 scored entities (PER, ORG, LOC), never used for training or for tuning
the rules. Scores are from the anonymizer pipeline (NER plus clean-up rules), with an exact match of start, end
and label required.

| Model | Precision | Recall | F1 | Recall on unseen names | F1 on new test customers |
| --- | --- | --- | --- | --- | --- |
| `de_core_news_lg` | 0.821 | 0.597 | 0.691 | 0.46 | 0.58 |
| previous version (epoch 1, 19.11.) | 0.873 | 0.765 | 0.816 | 0.54 | 0.66 |
| v4 | 0.838 | 0.790 | 0.814 | 0.59 | 0.75 |

Per label (v4): PER F1 0.88, ORG F1 0.76 (recall 0.66), LOC F1 0.64 (precision 0.50 on 19 places).
"Unseen names" are test entities whose text never occurs in the train split.

## Note on privacy

The training data includes texts and scanned letters from internal test stages. They contain names of employees
and test customers, and some letters may be copies of real mail with names of third parties. A NER model does not
store its training texts, but it can be biased towards names it has seen.
