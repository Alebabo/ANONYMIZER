# Cato 1.1: one German NER model for legal texts and support mails/chats

Cato replaces the two earlier fine-tuned models `de_legal_ner` (legal texts) and `de_custom_ner` (support mails and
chats), which both needed the 610 MB `de_core_news_lg`. Cato is a standalone spaCy 3.8 pipeline of about 43 MB
(tok2vec, tagger, morphologizer, attribute_ruler, ner); no spaCy model package has to be installed.

It is the only German model of OpenAnonymizer and part of the Docker image. The files come with Git LFS
(`git lfs pull`); `ANONYMIZER_CATO_PATH` points to another copy.

`meta.json` marks it as fine-tuned on chat text (`"anonymizer": {"casual": true}`), so lower-case chat entities are
kept, and the path contains `cato`, so the isolated-word check for signature lines runs (see `detect/ner.py`).

## Build

1. Base: `de_core_news_lg` with its word vectors pruned from 500,000 to 20,000 rows (every word keeps the nearest
   remaining vector), NER weights from `de_legal_ner` run 3 (in the Git history before Cato):
   `packages/core/scripts/ner_prune_base.py`.
2. Fine-tuning of the NER component, 6 epochs, best epoch 5 on the combined dev set (support gold dev + LER dev,
   F1 0.734 at the start, 0.787 after epoch 5; `training.json`):

   ```bash
   python -I packages/core/scripts/ner_train.py --base <base> --init <base> --dev both \
     --ler datasets/ler --courts datasets/courts --org-repeat 2 \
     --multiconer local/ner/public/hf/multiconer2/de_train.conll --multiconer-limit 4000 \
     --partial <ocr letters> --public datasets/public --epochs 6 --out <out>
   ```

   Data per epoch: German LER train (8,898 documents, those with an organisation twice more), 4,097 blocks of court
   decisions with synthetic names, GermEval 2014 (6,000 sentences), MultiCoNER v2 German (4,000), the German parts
   of SmartData, MAPA, E3-JSI and urchade (6,293 documents, `datasets/public`), 4,000 synthetic support texts, and
   internal support data (430 reviewed mails/chats x3, 340 partially labelled OCR letters x2). The internal data is
   not part of this repository.
3. Compaction: parser, lemmatizer and senter removed, string store emptied
   (`packages/core/scripts/ner_compact.py --name cato --version 1.1.0`). Checked: identical entities and POS tags
   to the uncompacted model on 200 LER dev documents.

## Results (test splits, full pipeline: rules + NER, 25.11.2026)

Compared with the best earlier model per dataset, both measured on the same code (including the rule for "Richter"
as a surname). LER: precision / recall, partial match. Finance sets: share of values masked (recall) / precision
lower bound.

| Dataset | Best earlier model | Earlier | Cato 1.1 | stock `de_core_news_lg` |
|---|---|---|---|---|
| German LER, all | `de_legal_ner` | 0.923 / 0.782 | 0.917 / 0.775 | 0.494 / 0.663 |
| German LER, persons | `de_legal_ner` | 0.914 / 0.914 | 0.904 / 0.904 | 0.611 / 0.741 |
| German LER, organisations | `de_legal_ner` | 0.883 / 0.538 | 0.886 / 0.522 | 0.324 / 0.399 |
| German LER, places | `de_legal_ner` | 0.967 / 0.864 | 0.958 / 0.868 | 0.512 / 0.838 |
| Court decisions, values found | `de_legal_ner` | 0.998 (persons 816/818) | 0.995 (814/818) | 0.992 (813/818) |
| Gretel finance DE | `de_custom_ner` | 0.744 / 0.324 | 0.697 / 0.306 | 0.724 / 0.318 |
| syntriq | `de_custom_ner` | 0.955 / 0.535 | 0.948 / 0.540 | 0.947 / 0.540 |
| EasyOctopus | `de_custom_ner` | 0.891 / 0.801 | 0.891 / 0.814 | 0.855 / 0.777 |

Cato does not reach the earlier adoption rule (recall at least as high as the best specialised model on every
test split). Recall is 0.3 to 1.6 points lower on LER, court decisions and syntriq and 4.7 points lower on Gretel; places and
EasyOctopus are at or above the earlier level, precision stays within 1 point except on Gretel (1.8). It was
adopted anyway (25.11.2026) to have one model for both domains at 43 instead of 616 MB. Against the stock
`de_core_news_lg` it is better on every dataset except Gretel, where the stock model masks more values
(0.724 vs. 0.697 recall).

## Next steps

- Gretel recall: more finance/bank examples in training (Gretel itself is test-only).
- Person recall on LER: the remaining misses are surnames after an article without a title ("der Günther").
- Several seeds; differences of a few hits from one run are noise.
