# Court decisions with synthetic values (legal NER training and recall check)

Whole decisions of local and regional courts (Amtsgerichte, Landgerichte, Oberlandesgerichte, labour,
administrative and social courts) from Open Legal Data, built by `packages/core/scripts/court_data.py`.
License: **ODbL 1.0** (see [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)); the rest of the repository
keeps its own license.

## Why, next to German LER

German LER has single sentences of federal decisions. Real legal documents carry personal data in the rubrum,
in party and witness names, addresses, bank details and the own file number, mostly at local courts. The
published decisions replace exactly those values by "…". `court_data.py build` fills every placeholder whose
context says what it was:

| Context (examples) | Label | Inserted |
|---|---|---|
| "Herr …", "Zeugin …", "des Sachverständigen …", "Rechtsanwälte …", "KHK …" | `PER` | name |
| "… GmbH", "M... H... & Co. KG", "Firma …", "… Bank", "Sparkasse …" | `ORG` | company |
| "12345 …", "in …", "Grundbuch von …", "Flug von … nach …" | `LOC` | city |
| "…straße 12", "Lindenstraße …" | `ADDR` | street and number |
| "geboren am …", "der am … verstorbene" | `DATE` | date |
| "Az. …", "Aktenzeichen …" | `AZ` | case number |
| "IBAN …", "Kontonummer …" | `IBAN` | valid IBAN |

A bare "…" without such context stays as it is. Train and dev/test use disjoint name lists; the split is by
decision.

## Size and results

1,240 downloaded decisions (`raw/`), 614 with filled placeholders: train 493, dev 65, test 56 decisions;
9,513 persons, 196 places, 109 organisations, 89 dates, 30 case numbers, 16 addresses, 14 IBANs.

Test split, inserted values found by the full detector (`eval_test.json` plain model,
`eval_test_de_legal_ner.json` fine-tuned): 0.988 -> **0.995**; persons 0.990 -> 0.995; organisations 9 of 9
(before the organisation rules of 21.11.2026: 7 of 9, "Fa. Schreiber e.K." was missed). Most of this comes from
the rules (names after "Herr", "Zeugin", "Rechtsanwalt" …, including García, Yıldız, Wójcik since 21.11.2026).

## Limits

Only the inserted values are labelled. A court sometimes leaves real names in the text (judges, often
lawyers), so these files measure **recall** and teach entities; **precision** is measured on German LER.
For training, `ner_train.py --courts` treats lower-case words and what the rules find (courts, citations,
case numbers) as "not an entity" and leaves other capitalised words out of the loss.

## Raw data

`raw/decisions.jsonl.gz` holds every downloaded decision as published (id, court, file number, date, type,
ECLI, HTML content; ODbL 1.0). `build` reads it when there is no local download, so the dataset can be rebuilt
and changed without calling the API again. The published decisions are anonymized by the courts; they contain
no data that is not already public.

## Use

```bash
python packages/core/scripts/court_data.py download    # more decisions to local/courts (polite, rate-limited)
python packages/core/scripts/court_data.py pack        # local/courts -> raw/decisions.jsonl.gz
python packages/core/scripts/court_data.py build
python packages/core/scripts/court_data.py eval --split test
```
