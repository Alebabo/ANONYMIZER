# Prompt: NER weitertrainieren und verkleinern (für Claude Code auf einem anderen Rechner)

Den Block unten in Claude Code einfügen, gestartet im Ordner des geklonten Repos.

````markdown
# Aufgabe: OpenAnonymizer-NER verbessern und verkleinern

## Einrichtung (zuerst, und prüfen, dass alles da ist)
1. `git lfs install` (sonst sind die Modellgewichte unter `models/**/model` nur Zeiger-Dateien von wenigen Bytes).
2. `git fetch && git switch feature/newmean-detector && git lfs pull`
3. Prüfen: `models/de_legal_ner/ner/model` und `models/de_custom_ner/ner/model` sind je etwa 6 MB groß.
4. Python 3.11+ und venv: `pip install -e "packages/core[dev]" pyarrow`
5. `python -m spacy download de_core_news_lg`, `de_core_news_md`, `en_core_web_lg`, `en_core_web_sm`
6. Daten im Repo (Git, kein Download nötig): `datasets/ler/*.jsonl.gz`, `datasets/courts/*.jsonl.gz`,
   `datasets/finance/raw/syntriq`, `datasets/finance/raw/easyoctopus`.
   Download nötig: Gretel mit `python packages/core/scripts/finance_data.py download`.
   Optional, öffentlich: GermEval 2014 nach `local/ner/public/germeval14/train.tsv`, MultiCoNER v2 Deutsch
   (`de_train.conll`) nach `local/ner/public/hf/multiconer2/`.
7. NICHT vorhanden und nie ins Repo: interne Trainingsdaten (`local/ner/gold.jsonl`, OCR-Briefe). Ohne sie wird
   nur mit öffentlichen Daten trainiert. Das ist so gewollt, nicht nach ihnen suchen.

Fehlt etwas aus 1–6, melde mir genau, was fehlt, statt weiterzumachen.

## Kontext
OpenAnonymizer pseudonymisiert deutsche Texte mit Regeln (`packages/core/src/anonymizer/detect/recognizers.py`,
`orgs.py`) plus spaCy-NER (`detect/ner.py`). Es gibt zwei feinjustierte NER-Komponenten (je 6 MB, Git LFS):
`models/de_legal_ner` (Rechtstexte) und `models/de_custom_ner` (Support-Mails und Chats). Beide setzen auf
`de_core_news_lg` auf (610 MB, davon 596 MB Wortvektoren). Mit `en_core_web_lg` (425 MB) ist die Installation
über 1 GB groß.

Lies zuerst `AGENTS.md`, `STATUS.md`, `docs/research/unified-ner-md.md` (Zwischenstand), `docs/research/newmean-pii.md`,
`models/de_legal_ner/README.md` und `models/de_custom_ner/README.md`.

## Ziel
1. Ein gemeinsames NER-Modell für Legal und Support statt zwei getrennter.
2. Basis `de_core_news_md` (60 MB) statt `de_core_news_lg`, Englisch über `ANONYMIZER_NER_MODEL_EN=en_core_web_sm`.
3. Höchstmöglicher Recall, zuerst Personen, dann Firmen (größte Lücke: LER 117 von 253 Firmen übersehen).

## Übernahmeregel (verbindlich)
Übernehmen nur, wenn auf ALLEN Test-Splits der Recall mindestens so hoch ist wie beim bisher besten Spezialmodell und
die Precision höchstens 2 Punkte darunter liegt.

| Datensatz | bestes bisheriges Modell | Precision / Recall |
|---|---|---|
| German LER gesamt (PER/ORG/LOC, partiell) | `de_legal_ner` | 0,923 / 0,782 |
| German LER Personen | `de_legal_ner` | 0,914 / 0,914 |
| German LER Firmen | `de_legal_ner` | 0,883 / 0,538 |
| German LER Orte | `de_legal_ner` | 0,967 / 0,864 |
| Gerichtsentscheidungen | `de_legal_ner` | Recall 0,995, Personen 814 von 818 |
| Gretel Finance DE | `de_custom_ner` | Recall 0,744 / Precision-Untergrenze 0,324 |
| syntriq | `de_custom_ner` | 0,955 / 0,535 |
| EasyOctopus | `de_custom_ner` | 0,891 / 0,801 |

Die Werte wurden vor der neuen Regel „Richter als Nachname“ gemessen. Deshalb zuerst die Baseline auf diesem Branch
nachmessen. Abweichungen musst du erklären können.

## Messen
Jede Messung in eine Kopie der Daten schreiben (die Skripte überschreiben `eval_*.json` im Datenordner):
```bash
# ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_legal_ner/ner"     (Baseline Legal)
# ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_custom_ner/ner"    (Baseline Support)
# ANONYMIZER_NER_MODEL_DE="de_core_news_md+local/ner/models/<name>/ner" (neues Modell)
python packages/core/scripts/ler_data.py eval --split test --data <kopie>/ler
python packages/core/scripts/court_data.py eval --split test --data <kopie>/courts
python packages/core/scripts/finance_data.py eval --data <kopie>/finance
```
Die Einzelwort-Prüfung für Unterschriftenzeilen (`_ISOLATED_MODELS` in `detect/ner.py`) läuft nur, wenn der
Modellpfad `de_legal_ner` enthält. Beim gemeinsamen Modell mit und ohne messen.

## Trainieren (nur öffentliche Daten)
```bash
python packages/core/scripts/ner_train.py --base de_core_news_md \
  --ler datasets/ler --courts datasets/courts --org-repeat 2 --epochs 6 \
  --out local/ner/models/de_unified_ner_md_public
# optional: --multiconer local/ner/public/hf/multiconer2/de_train.conll --multiconer-limit 4000
# GermEval wird automatisch genutzt, wenn local/ner/public/germeval14/train.tsv existiert
```
Ohne interne Daten fehlt der Support-Anteil. Deshalb `--synthetic` (Vorlagen in `ner_train.py`) nutzen und auf den
Finanzdatensätzen gegenprüfen.

## Vorgehen
1. Einrichtung prüfen und Baseline messen.
2. Fehleranalyse NUR auf Train- und Dev-Splits (`--split dev`, `errors_dev.md`), nie auf Test.
3. Regeln für wiederkehrende Muster. Bekannte Restfehler: Nachname nach Artikel ohne Anrede („der Günther“),
   Verbandskürzel und Marken als Firma, Bindestrich-Namen, Namen mit Partikel, USt-IdNr. mit Leerzeichen
   (`DE 298 765 432`) in der Regel `vat_id`.
4. Trainieren, alle drei Messungen, Tabelle gegen die Messlatte.
5. Mehrere Seeds oder Varianten. Unterschiede von 5–6 Treffern aus einem einzigen Lauf sind Rauschen.
6. Erst bei erfüllter Übernahmeregel: Modell nach `models/<name>/ner` (nur die `ner`-Komponente, Git LFS), README mit
   Trainingsbefehl und Messwerten, `STATUS.md` aktualisieren.

## Regeln
- Alle Tests grün (`cd packages/core && pytest`), Typecheck `npx tsc --noEmit -p .`.
- Keine Firmen- oder Produktnamen meines Arbeitgebers und keine internen Chatbot-Namen ins Repo. Bei Beispielen
  ACME / ACMECOMPARE verwenden. Keine echten Personendaten committen.
- Commit-Autor `Alebabo@users.noreply.github.com` (repo-lokal setzen). Nur auf dem Feature-Branch committen, nur nach
  meiner Freigabe pushen.
- Mit mir auf Deutsch, sachlich, ohne Emojis. Lange Trainings im Hintergrund, Stand zwischendurch kurz melden.

## Ergebnis
Tabelle „Messlatte gegen neues Modell“ für alle Datensätze, Installationsgröße in MB, Laufzeit je Datensatz und eine
klare Empfehlung (übernehmen ja/nein mit Begründung).
````
