# de_c24_ner: fine-tuned German NER for support mails and chats

NER weights for spaCy `de_core_news_lg` (3.8), fine-tuned on bank support text. Only the `ner` component is
stored here (about 6 MB). Word vectors, tagger and the other components come from the base model, which must be
installed (`python -m spacy download de_core_news_lg`).

**Status: work in progress.** This is the checkpoint after epoch 1 of a running training (19.11.2026). It
will be replaced by the best epoch once training has finished.

## Use

```bash
ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_c24_ner/ner"
```

The path is relative to the working directory of the process. Without the variable the anonymizer uses the
plain `de_core_news_lg`.

## Training data

- GermEval 2014 NER (public, CC BY 4.0), 6,000 sentences, so the model keeps its general German NER.
- 4,000 synthetic support texts from templates (signatures, greetings, mail headers, payees, courts,
  lower-case chat). The names, organisations and places used never occur in the dev or test split.
- 222 annotated mails and chats from the sbx and int test stages (train split, repeated 3 times).

Training and evaluation scripts: `packages/core/scripts/ner_train.py` and `packages/core/scripts/ner_gold.py`.
The annotated data is not part of this repository.

## Results

Held-out test split: 494 sbx/int documents, 239 scored entities (PER, ORG, LOC). Scores are from the
anonymizer pipeline (NER plus clean-up rules), with an exact match of start, end and label required.

| Model | Precision | Recall | F1 |
| --- | --- | --- | --- |
| `de_core_news_lg`, old rules | 0.723 | 0.569 | 0.637 |
| `de_core_news_lg`, new rules | 0.848 | 0.632 | 0.724 |
| this checkpoint, new rules | 0.898 | 0.812 | 0.853 |

On test entities whose text never occurs in the train split, recall rises from 0.453 to 0.523. Part of the gain
comes from names that recur in the test stages, for example employee signatures.

## Note on privacy

The train split contains texts from internal test stages. They include names of employees and test customers.
A NER model does not store its training texts, but it can be biased towards names it has seen.
