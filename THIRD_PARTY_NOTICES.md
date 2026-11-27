# Third-party notices

## Langfuse (MIT)

The dashboard design tokens (`app/globals.css`) and the UI primitives in
`components/ui/` (button, card, table, input) are derived from
https://github.com/langfuse/langfuse (`web/src/styles/globals.css`,
`web/src/components/ui/`). Only files outside Langfuse's `ee/` directories
were used. The audit log record shape (`packages/core/src/anonymizer/audit.py`:
resource type/id, action, before/after, actor) follows Langfuse's
`web/src/features/audit-logs/auditLog.ts` (MIT). The audit log viewer is OpenAnonymizer's
own implementation; Langfuse's viewer lives in `ee/` and was not used.
License text as distributed by Langfuse:

```
Copyright (c) 2023-2026 ClickHouse, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## German LER dataset (CC BY 4.0)

`datasets/ler/` is derived from the German Legal Entity Recognition dataset by Elena Leitner, Georg Rehm and
Julián Moreno-Schneider (2019), https://github.com/elenanereiss/Legal-Entity-Recognition, licensed under
CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Changes: tokens joined into running text, sentences
grouped into documents, labels mapped to OpenAnonymizer's types, and anonymized names, companies and places in
the published decisions replaced by synthetic values (`packages/core/src/anonymizer/ler.py`). The underlying
court decisions are official works without copyright (§ 5 UrhG).

## Open Legal Data (ODbL 1.0)

`datasets/courts/` is derived from court decisions retrieved through the Open Legal Data API
(https://de.openlegaldata.io). The decisions themselves are official works without copyright (§ 5 UrhG); the
Open Legal Data database is licensed under the Open Database License 1.0
(https://opendatacommons.org/licenses/odbl/1-0/). The derived dataset in `datasets/courts/` is therefore made
available under ODbL 1.0 as well. Changes: HTML converted to text, and the courts' anonymization placeholders
("…") replaced by synthetic names, companies, places, dates, case numbers and IBANs
(`packages/core/src/anonymizer/courts.py`). The rest of this repository is not affected by this license.

`datasets/outcome/` (Machbarkeitsexperiment Kündigungsschutz-Prognose) is derived from the Hugging Face dataset
`openlegaldata/court-decisions-germany` (dump-20260520), i.e. the same Open Legal Data database, and is likewise
made available under ODbL 1.0. Access to the source dataset on Hugging Face is gated (a Hugging Face account
that has accepted the dataset's conditions is required). `datasets/outcome/raw/decisions.jsonl.gz` contains 3,226
labour court judgments in derived form: ids, court, date, file number, the operative part (ArbG) or the summary of
the first-instance judgment (LAG), a cleaned statement of facts (dates, file numbers and outcome sentences
removed), the extracted outcome label and the split assignment. `labels.csv` and `results.json` are derived from
it. Changes: HTML converted to text, sections cut, sentences removed, labels added
(`packages/core/scripts/outcome_experiment.py`).

## Financial PII datasets (Apache-2.0)

`datasets/finance/raw/` contains unchanged copies (German parts) of two synthetic datasets licensed under the
Apache License 2.0, each with its license or dataset card next to the data: syntriq/german-pii-benchmark
(Syntriq) and EasyOctopus/german-support-pii-data (EasyOctopus; see its NOTICE file). A third,
gretelai/synthetic_pii_finance_multilingual (Gretel.ai, Apache-2.0), is downloaded on demand and not committed.

## GermEval 2014 NER (CC BY 4.0)

`packages/core/src/anonymizer/detect/data/common_nouns_de.txt` and `common_words_de.txt` are word lists derived
from the train split of the GermEval 2014 NER dataset (Benikova, Biemann, Reznicek 2014,
https://sites.google.com/site/germeval2014ner/), licensed under CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). Changes: only word forms with their frequency outside entities
were kept (`packages/core/scripts/build_common_nouns.py`); no sentences are included. GermEval 2014 sentences
were also used to train the NER weights in `packages/core/models/cato-1.1/` (not distributed as text).

## MultiCoNER v2 (CC BY 4.0)

The NER weights in `packages/core/models/cato-1.1/` were trained, among other data, on 4,000 sentences of the
German part of MultiCoNER v2 (Fetahu, Chen, Kar, Rokhlenko, Malmasi 2023, https://multiconer.github.io,
https://huggingface.co/datasets/MultiCoNER/multiconer_v2), licensed under CC BY 4.0. Changes: fine-grained labels
mapped to PER/ORG/LOC (`load_multiconer` in `packages/core/scripts/ner_train.py`). The data itself is not part of
this repository. CoNLL-2003 is not used anywhere in this repository (licence for research only).

## Public PII and NER datasets (CC BY 4.0, MIT, Apache-2.0)

`datasets/public/` contains the German parts of four datasets in converted form (`{id, text, entities}` per
document, labels mapped to OpenAnonymizer types, person spans without salutation or title, labels without personal
data dropped; `packages/core/scripts/public_pii.py`). They are used to measure the detector and, through
`ner_train.py --public`, as NER training data.

- SmartData Corpus (Schiersch, Mironova, Schmitt, Thomas, Gabryszak, Hennig 2018, DFKI,
  https://huggingface.co/datasets/DFKI-SLT/smartdata-corpus), CC BY 4.0. Changes: tokens detokenized,
  labels mapped; validation split not included.
- MAPA EUR-Lex corpus (MAPA project 2022, https://mapa-project.eu,
  Hugging Face conversion https://huggingface.co/datasets/joelniklaus/mapa), CC BY 4.0. Changes: German sentences
  only, tokens detokenized, coarse labels mapped, titles/roles/nationalities removed from person spans.
- E3-JSI/synthetic-multi-pii-ner-v1 (Jožef Stefan Institute, https://huggingface.co/datasets/E3-JSI/synthetic-multi-pii-ner-v1),
  MIT License. Changes: German documents only, token spans converted to character offsets, labels mapped, every
  fifth document (by text hash) held out as test split.
- urchade/synthetic-pii-ner-mistral-v1 (Urchade Zaratiana, https://huggingface.co/datasets/urchade/synthetic-pii-ner-mistral-v1),
  Apache License 2.0. Changes: German documents only (picked by function words), tokens detokenized, labels
  mapped, every fifth document (by text hash) held out as test split.

Not used: ai4privacy/open-pii-masking-500k (Llama Community License terms and written permission for commercial use).

## Optional GLiNER models (not distributed)

`packages/core/src/anonymizer/detect/gliner_ner.py` can use a GLiNER model as an optional second NER detector
(off by default; extra `anonymizer-core[gliner]`, library `gliner`, Apache-2.0). No model weights are included in
this repository; a model is downloaded by the user from Hugging Face or loaded from a local path. Models measured in
`docs/research/gliner-results.md`, all Apache-2.0: `urchade/gliner_multi-v2.1` and `urchade/gliner_multi_pii-v1`
(base encoder `microsoft/mdeberta-v3-base`, MIT), `knowledgator/gliner-x-small` (base encoder `google/mt5-small`,
Apache-2.0; needs `stanza` and `langdetect`, both Apache-2.0). Do not use `urchade/gliner_multi` (v0, CC BY-NC 4.0).

## spaCy de_core_news_lg (MIT)

`packages/core/models/cato-1.1/` is derived from the spaCy pipeline `de_core_news_lg` 3.8.0 (Explosion AI,
https://github.com/explosion/spacy-models, MIT licence, Copyright (c) Explosion AI). Changes: word vectors pruned
from 500,000 to 20,000 rows (`packages/core/scripts/ner_prune_base.py`), parser, lemmatizer and senter removed,
string store emptied (`packages/core/scripts/ner_compact.py`), NER component fine-tuned. The tok2vec, tagger,
morphologizer and attribute_ruler components and the remaining vectors are unchanged from the original. The MIT
licence text: https://github.com/explosion/spacy-models/blob/master/LICENSE.

## OCR: Tesseract, pdfium, xterm.js, node-pty

- Tesseract OCR and its German language data (`tesseract-ocr`, `tesseract-ocr-deu`), Apache-2.0,
  https://github.com/tesseract-ocr/tesseract. Installed as a system package, not redistributed in this repository.
- pypdfium2 (Apache-2.0 / BSD-3-Clause) with PDFium (BSD-3-Clause/Apache-2.0), used to render scanned PDF pages.
- Pillow (MIT-CMU / HPND), image conversion for OCR.
- Arca prototype: xterm.js (`@xterm/xterm`, `@xterm/addon-fit`, `@xterm/addon-web-links`, `@xterm/addon-clipboard`, MIT; js-base64, BSD-3-Clause), node-pty (MIT), ws (MIT).
