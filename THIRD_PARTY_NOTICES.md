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
