# Gemeinsames NER-Modell: von de_core_news_md zu Cato 1.1

## Ergebnis 25.11.2026
Übernommen als **Cato 1.1** (`packages/core/models/cato-1.1`, 43 MB, Werte und Bau im README dort). Varianten, alle mit
`--public datasets/public` und Einzelwort-Prüfung gemessen (Test-Splits, LER P/R, Finanz R):

| Variante | Dev F1 | LER | LER Personen R | Gretel R | EasyOctopus R |
|---|---|---|---|---|---|
| md, Start `de_unified_ner_md`, Epoche 5 | 0,768 | 0,902 / 0,771 | 0,898 | 0,694 | 0,875 |
| lg-Vektoren auf 20.000 Zeilen, Start `de_legal_ner`, Epoche 2 | 0,774 | 0,905 / 0,766 | 0,898 | 0,693 | 0,879 |
| **dieselbe, Epoche 5 (Cato 1.1)** | **0,787** | **0,917 / 0,775** | **0,904** | **0,697** | **0,891** |
| lg-Vektoren gekürzt, Start `de_custom_ner` | 0,763 (Epoche 3) | nicht gemessen | | | |

Die gekürzten lg-Vektoren behalten den Vektorraum, auf dem `de_legal_ner` trainiert war; das zahlte sich nach
mehreren Epochen aus. Die Übernahmeregel (Recall nirgends unter dem besten Spezialmodell) ist nicht erfüllt
(Gretel −4,7, LER/Gerichte/syntriq −0,3 bis −1,6 Punkte; auf Gretel liegt auch `de_core_news_lg` mit 0,724 vorn); auf Wunsch trotzdem übernommen.

# Zwischenstand 24.11.2026 (Verlauf)

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

## Kompaktes Modell unter 50 MB (25.11.)
`packages/core/scripts/ner_compact.py` macht aus der trainierten Pipeline ein eigenständiges Verzeichnis ohne
installiertes `de_core_news_md`: Parser, Lemmatizer und Senter fallen weg (der Anonymizer braucht nur NER und POS),
`vocab/strings.json` wird geleert (20 MB Text der 500.000 Vektor-Schlüssel; der Vektor-Lookup läuft über den Hash).
Vektoren und Gewichte bleiben unverändert.

- Epoche-2-Modell: 65,2 MB auf 43,6 MB.
- Prüfung im Skript (`--check`): 830 Texte aus LER-Dev, SmartData- und MAPA-Test, Entitäten und POS identisch.
- `finance_data.py eval --limit 150` mit `de_core_news_md+…/ner` und mit dem Kompaktmodell: Ergebnisse identisch.
- Nutzung: `ANONYMIZER_NER_MODEL_DE=<Kompaktordner>`. `meta.json` trägt `"anonymizer": {"casual": true}`, damit
  der Recognizer es wie ein feinjustiertes `base+ner`-Modell behandelt (kleingeschriebene Spans bleiben).

```bash
python -I packages/core/scripts/ner_compact.py local/ner/models/de_unified_ner_md_e6 \
  local/ner/models/de_unified_ner_md_compact --check datasets/ler/ler_dev.jsonl.gz datasets/public/smartdata/test.jsonl.gz
```

Weitere Reserve, falls nötig: seltene Vektor-Schlüssel streichen (`key2row` 6 MB) oder Vektoren auf weniger Zeilen
kürzen. Beides ändert die Vorhersagen und muss dann neu gemessen werden.

## Weitere offene Punkte
- Erledigt (24.11.): USt-IdNr. mit Leerzeichen (`DE 298 765 432`, `ATU 12345678`) erkennt die Regel `vat_id` jetzt.
- Neue öffentliche Trainingsdaten in `datasets/public/` (SmartData, MAPA, E3-JSI, urchade; `public_pii.py`). Für den
  nächsten Lauf `--public datasets/public` anhängen (ca. 6.300 Dokumente, PER/ORG/LOC; Behörden/Gerichte und
  Adressen bleiben aus dem Loss). Ohne interne Daten unter `local/` geht ein Lauf damit nur auf öffentlichen Quellen.
- Bekannte Personen-Restfehler auf Dev: Nachname nach Artikel ohne Anrede („der Günther“), LER-Platzhalter.
- Das Modell selbst ist nicht im Repo (trainiert auch auf internen Daten unter `local/`). Ohne diese Daten nur mit öffentlichen Quellen trainieren (LER, Gerichtsentscheidungen, GermEval, MultiCoNER, synthetisch).
