# de_legal_ner: German NER for legal texts

NER weights for spaCy `de_core_news_lg` (3.8), fine-tuned on court decisions. Only the `ner` component is
stored (about 6 MB, Git LFS); vectors, tagger etc. come from the base model
(`python -m spacy download de_core_news_lg`).

```bash
ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_legal_ner/ner"
```

Training data and measurement: [datasets/ler](../../datasets/ler/README.md),
[datasets/courts](../../datasets/courts/README.md); `training.json` holds the run.
