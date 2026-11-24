# Gemeinsames NER-Modell auf de_core_news_md: Zwischenstand 24.11.2026

## Git
- Branch `feature/newmean-detector`, gepusht (Commits 168415d, aa2bc8b). Lokal nur `logs/` offen.
- Enthält: newmean-pii-Detektor (optional, für Legal nicht empfohlen, `docs/research/newmean-pii.md`),
  `ner_train.py --base/--dev both`, `ANONYMIZER_NER_MODEL_EN`, Regel „Richter“ als Nachname, `/v1/protect output: text`.

## Laufendes Training (abgebrochen durch Herunterfahren)
Gemeinsames Modell Bank + Legal auf `de_core_news_md`, Ziel 6 Epochen. Gespeichert ist das beste Modell nach
Epoche 2 in `local/ner/models/de_unified_ner_md` (volle Pipeline, NER in `ner/`). Log: `local/ner/train_unified_md.log`.

| | Dev F1 | P | R |
|---|---|---|---|
| Start (md ohne Training) | 0,384 | 0,292 | 0,558 |
| Epoche 1 | 0,745 | 0,811 | 0,689 |
| Epoche 2 | 0,756 | 0,826 | 0,697 |

Fortsetzen (4 weitere Epochen ab Epoche 2, neuer Ausgabeordner, damit Epoche 2 erhalten bleibt):
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -I packages/core/scripts/ner_train.py --base de_core_news_md \
  --init local/ner/models/de_unified_ner_md --dev both --ler datasets/ler --courts datasets/courts --org-repeat 2 \
  --multiconer local/ner/public/hf/multiconer2/de_train.conll --multiconer-limit 4000 \
  --partial local/ner/partial_ocr.json local/ner/partial_ocr_sbx.json --epochs 4 \
  --out local/ner/models/de_unified_ner_md_e6 > local/ner/train_unified_md_e6.log 2>&1
```

## Danach messen (Test-Splits, jeweils in Datenkopie)
`ANONYMIZER_NER_MODEL_DE="de_core_news_md+local/ner/models/<name>/ner"`, dann `ler_data.py eval --split test`,
`court_data.py eval --split test`, `finance_data.py eval` (pyarrow ist installiert, Gretel heruntergeladen).
Einmal mit Pfadname, der `de_legal_ner` enthält (Einzelwort-Prüfung an), einmal ohne.

Messlatte (Recall mindestens gleich, Precision höchstens 2 Punkte darunter):

| Datensatz | Modell | Wert |
|---|---|---|
| LER gesamt P / R | de_legal_ner | 0,923 / 0,782 |
| LER Personen P / R | de_legal_ner | 0,914 / 0,914 |
| LER Firmen P / R | de_legal_ner | 0,883 / 0,538 |
| Gerichtsentscheidungen | de_legal_ner | 0,995, Personen 814/818 |
| Gretel R / P | de_custom_ner | 0,744 / 0,324 |
| syntriq R / P | de_custom_ner | 0,955 / 0,535 |
| EasyOctopus R / P | de_custom_ner | 0,891 / 0,801 |

Die Regel „Richter“ ist neu, die Messlatte stammt von vorher. Für einen fairen Vergleich die Baseline mit der neuen
Regel nachmessen.

## Weitere offene Punkte
- USt-IdNr. mit Leerzeichen (`DE 298 765 432`) erkennt die Regel `vat_id` nicht (newmean schon).
- Bekannte Personen-Restfehler auf Dev: Nachname nach Artikel ohne Anrede („der Günther“), LER-Platzhalter.
- Das Modell selbst ist nicht im Repo (trainiert auch auf internen Daten unter `local/`). Ohne diese Daten nur mit öffentlichen Quellen trainieren (LER, Gerichtsentscheidungen, GermEval, MultiCoNER, synthetisch).
