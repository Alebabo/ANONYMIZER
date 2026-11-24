# newmean-pii als optionaler zweiter Detektor

Stand: 24.11.2026, Paket `newmean-pii` 1.6.1, Modelle v1.1.0.

## Was es ist

newmean-pii ist ein kleines mehrsprachiges PII-Modell von newmean.ai (Token-Klassifikation, BIO). Es läuft
vollständig lokal (C-Erweiterung, keine weiteren Abhängigkeiten). Die Modelldateien werden beim ersten Start von
Hugging Face geladen und gegen fest hinterlegte SHA-256-Werte geprüft.

| Größe | Parameter | Datei |
|---|---|---|
| nano | 3,1 Mio. | 2,6 MB |
| small | 9,6 Mio. | 7,1 MB |
| medium (Standard im Paket) | 17,7 Mio. | 11,3 MB |
| large | 24,4 Mio. | 15,5 MB |

- Basis: mMiniLMv2-L6-H384 mit gekürztem XLM-R-Vokabular. Destilliert aus zwei nicht veröffentlichten Lehrermodellen
  (mDeBERTa-v3-base, XLM-R-large).
- 54 Sprachen. Eine Sprachliste ist nicht veröffentlicht, Deutsch ist nicht ausdrücklich bestätigt.
- 13 Labels: `PERSON`, `PERSON_L2`, `EMAIL`, `PHONE`, `ADDRESS`, `ID_NUMBER`, `FINANCIAL`, `ORG`, `USERNAME`,
  `URL`, `URL_L2`, `DATE_OF_BIRTH`, `SECRET`. Kein Score je Span.
- Lizenz: Code und Gewichte Apache-2.0. Testdatensatz CC BY-NC 4.0 (hier nicht genutzt).
- Weitertrainieren: nicht möglich. Veröffentlicht sind nur 4-Bit-ONNX-Dateien, keine Originalgewichte. Trainingsdaten und
  Datengenerator sind nicht öffentlich.

## Herstellerangaben

Kennzahl ist der Anteil nicht maskierter PII-Zeichen (Miss) und der Anteil fälschlich maskierter Nicht-PII-Zeichen
(Over-Masking). Alle Werte stammen vom Hersteller, Einzelläufe, nicht unabhängig geprüft.

| Datensatz | large: Miss / Over-Masking |
|---|---|
| eigener Testsatz (54 Sprachen, synthetisch, von Claude erzeugt, ähnlich den Trainingsdaten) | 1,6 % / 0,5 % |
| KDPII (Koreanisch) | 9,6 % / 1,7 % |
| openpii (30 Sprachen) | 4,9 % / 4,1 % |
| Nemotron-PII (Englisch) | 6,1 % / 1,6 % |
| Gretel Finance | 21,4 % / 5,5 % |

Geschwindigkeit laut Hersteller: etwa 10 ms für einen kurzen Text (medium, ein Thread, Apple M5 Pro), 0,35 s für
1.000 Tokens.

## Einbindung

Aus, solange kein Modell gesetzt ist. Spans laufen wie bei GLiNER durch dieselben Filter wie spaCy-Spans
(`authority_type`, `clean_entity`, NER-Stoppwörter) und verlieren jede Überlappung gegen Regeln und spaCy. newmean
ergänzt also nur Spans, die sonst niemand findet. Labels ohne eigenen OpenAnonymizer-Typ werden als `id_number`,
`financial`, `username`, `url`, `secret` übernommen; die Policies schwärzen sie über `default_action`.

```bash
pip install "anonymizer-core[newmean]"     # oder: pip install newmean-pii
```

| Einstellung | Umgebungsvariable | Standard |
|---|---|---|
| `DetectorConfig.newmean_model` | `ANONYMIZER_NEWMEAN_MODEL` (`nano`, `small`, `medium`, `large`) | leer = aus |
| `DetectorConfig.newmean_labels` | `ANONYMIZER_NEWMEAN_LABELS` (z. B. `PERSON,ORG,ID_NUMBER`) | alle |
| `DetectorConfig.newmean_sensitivity` | `ANONYMIZER_NEWMEAN_SENSITIVITY` (-1 bis 1, höher = mehr maskieren) | 0 |
| `DetectorConfig.newmean_model_dir` | `ANONYMIZER_NEWMEAN_MODEL_DIR` (Ordner für Offline-Betrieb) | leer = Download |

Im Betrieb ohne Internet: Modell vorab mit `python -c "from newmean_pii import fetch_model; fetch_model('large')"`
laden und den Ordner aus `~/.cache/newmean-pii` als `ANONYMIZER_NEWMEAN_MODEL_DIR` setzen. Mit `disabled_recognizers:
["newmean"]` lässt es sich je Konfiguration abschalten.

## Eigene Messung

24.11.2026, Test-Splits, Basis `de_core_news_lg` ohne `de_custom_ner` (Standard ohne `ANONYMIZER_NER_MODEL_DE`),
newmean `large`, alle Labels, Sensitivität 0. Windows-CPU; beide Läufe liefen parallel.

| | ohne newmean | mit newmean large |
|---|---|---|
| German LER, partiell: Precision / Recall / F1 | 0,494 / 0,663 / 0,566 | 0,366 / 0,697 / 0,480 |
| German LER, Personen: Precision / Recall | 0,611 / 0,741 | 0,316 / 0,809 |
| German LER, Personen: TP / FP | 240 / 153 | 262 / 568 |
| German LER, Firmen: Precision / Recall | 0,324 / 0,399 | 0,324 / 0,423 |
| German LER, Orte | 0,512 / 0,838 | unverändert |
| Gerichtsentscheidungen: Recall gesamt / Personen | 0,990 / 811 von 818 | 0,993 / 814 von 818 |
| Laufzeit LER (1.113 Dok., 1,4 Mio. Zeichen) | 46 s | 1.315 s (29-fach) |
| Laufzeit Gerichtsentscheidungen (56 Dok., 1,4 Mio. Zeichen) | 51 s | 1.853 s (36-fach) |

Einordnung:
- newmean findet 22 Personen mehr, markiert dafür 415 Nicht-Personen zusätzlich als Person. Die Personen-Precision
  halbiert sich. Das verletzt die Übernahmeregel (Precision darf nicht sinken).
- Bei Firmen ein kleiner Gewinn (+6 Treffer), bei Orten keine Änderung.
- Rechtsprechungszitate werden öfter als Person markiert (`PER on RS` 29 -> 75).
- Laufzeit: rund 1 s je 1.000 Zeichen statt rund 0,03 s. Für lange Schriftsätze im Chat oder über MCP nicht vertretbar.

Handverlesene Legal-Fälle (Rubrum, Spruchkörper, Normzitate, Mandantenmail, Handelsregister, Zeuge, Bankverbindung):
newmean allein findet Namen, Adressen, Telefon, Steuer-ID, IBAN und BIC, aber keine Gerichte, Aktenzeichen, Normzitate
oder Gesundheitsangaben, im Rubrum weder die beklagte GmbH noch ihren Geschäftsführer. Einziger Zusatztreffer gegenüber
OpenAnonymizer: eine USt-IdNr. mit Leerzeichen (`DE 298 765 432`), die die Regel `vat_id` nicht erkennt.

Zum Vergleich die Rechtskonfiguration (`ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_legal_ner/ner"`, ohne
newmean): LER Precision / Recall 0,923 / 0,782, Personen 296 richtig / 28 falsch / 28 übersehen (0,914 / 0,914),
Gerichtsentscheidungen 814 von 818 Personen. Sie liegt damit bei Personen deutlich vor newmean (262 richtig / 568 falsch).

Empfehlung: für Legal aus lassen. Die USt-IdNr.-Lücke besser in der Regel schließen.

## Links

- Demo: https://pii.newmean.ai/
- Code, README, Ergebnisse: https://github.com/newmean-ai/pii
- Technischer Bericht: https://github.com/newmean-ai/pii/blob/main/docs/report/REPORT.md
- Trainingsskripte: https://github.com/newmean-ai/pii/tree/main/training
- Modelle: https://huggingface.co/newmean-ai (z. B. https://huggingface.co/newmean-ai/pii-medium)
- Testdatensatz: https://huggingface.co/datasets/newmean-ai/pii-dataset
- Leaderboard: https://huggingface.co/spaces/newmean-ai/pii-leaderboard
- Python-Paket: https://pypi.org/project/newmean-pii/
