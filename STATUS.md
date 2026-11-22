# Projektstand OpenAnonymizer

Stand: 21.11.2026. Übergabe für die Weiterarbeit, auch durch andere Coding-Agents (Codex, Claude Code).
Hintergrund und Architekturentscheidungen: [plan.md](plan.md). Betrieb in einer Firma:
[HANDOVER.md](HANDOVER.md).

## 1. Was das Produkt ist

Ein Datenschutz-Layer für KI: Texte werden **vor** dem KI-Modell erkannt, klassifiziert und nach einer
deterministischen Policy pseudonymisiert (`PERSON_001`, `CASE_NUMBER_001` …). Aktueller Fokus:
**juristische Texte / Kanzleien** (§ 203 StGB, DSGVO).

Ein Modell, drei Wege, es zu nutzen, alle in den Traces protokolliert (Kanal `api` | `mcp` | `dashboard`, Key/Nutzer):

| Weg | Wie |
|---|---|
| Dashboard-Chat | Startseite: Text eingeben, sehen, was die KI bekäme; Erkennung korrigieren (Feedback) |
| REST | `POST /v1/protect`, `/v1/scan`, `/v1/anonymize`; Policy-Test `POST /v1/policies/{name}/test` |
| MCP | `/mcp` (HTTP, Bearer-Key), Tool `anonymize_content`; nutzt dieselbe gespeicherte Policy wie die API |

## 2. Repository

| Pfad | Inhalt |
|---|---|
| `packages/core/` | Python-Paket `anonymizer-core`: Erkennung, Policy, API (FastAPI), MCP, CLI, Tests |
| `packages/core/src/anonymizer/detect/` | Regeln (`recognizers.py`), Kontextsignale (`context.py`), spaCy-NER (`ner.py`) |
| `packages/core/src/anonymizer/policy/builtin/` | `banking-default`, `support-default`, **`legal-default`** |
| `packages/core/src/anonymizer/{ler,courts,feedback}.py` | Trainingsdaten (German LER, Gerichtsentscheidungen), Feedback-Speicher |
| `packages/core/scripts/` | `ler_data.py`, `court_data.py` (Daten bauen/messen), `ner_train.py` (Training), `ner_gold.py`, `local_eval.py` (Mess-Kit echte Kanzleitexte, `docs/local-eval.md`) |
| `app/`, `components/`, `lib/` | Next.js-Dashboard: Tabs **Chat**, **Traces**, **CSV**; Settings: Policies, API Keys, Members, Feedback, Audit Logs |
| `models/de_legal_ner/` | Feinjustierte NER-Gewichte für Rechtstexte (Git LFS, ~6 MB) |
| `models/de_custom_ner/` | Feinjustierte NER-Gewichte für Support-Mails/Chats (Git LFS) |
| `datasets/ler/` | German LER (CC BY 4.0): Rohdaten `raw/`, Gold-JSONL, Auswertungen |
| `datasets/courts/` | 1.240 Entscheidungen von Open Legal Data (ODbL 1.0): Rohdaten `raw/`, Gold-JSONL mit synthetischen Werten |
| `datasets/finance/` | Drei synthetische Finanz-/Bank-/Support-Datensätze (Apache-2.0) zur Messung, `finance_data.py eval` |
| `docs/research/` | Recherchen: `outcome-prediction.md`, `org-ner.md`, `org-ner-results.md`, `person-recall.md`, `gliner-results.md` |
| `datasets/outcome/` | Machbarkeitsexperiment Ausgangsvorhersage Kündigungsschutz (3.226 Urteile, ODbL), `outcome_experiment.py` |

## 3. Aktuelle Qualität (Test-Splits, komplette Pipeline)

Rechtstexte mit `ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_legal_ner/ner"`:

| | vorher | jetzt |
|---|---|---|
| German LER: Präzision / Recall (Personen, Firmen, Orte) | 0,32 / 0,63 | **0,92 / 0,78** |
| Personen P / R | 0,42 / 0,74 | 0,91 / **0,91** |
| Firmen P / R | 0,23 / 0,30 | 0,88 / **0,54** ← größte Schwäche |
| Orte P / R | 0,28 / 0,83 | 0,97 / 0,86 |
| Falsche Treffer auf Gerichten, Gesetzen, Zitaten | 773 | 18 |
| Gesetzeszitate / Gerichte / Aktenzeichen erkannt | 0,38 / 0,69 / 0,81 | 0,92 / 0,97 / 1,00 |
| Gerichtsentscheidungen: eingesetzte Werte gefunden | – | 0,995 |

Finanz- und Banktexte (`datasets/finance`, ohne Rechtsmodell): geschützt werden auf syntriq 0,905, EasyOctopus
0,586, Gretel 0,654 der Werte (vorher 0,808 / 0,398 / 0,636). Neu erkannt: Telefon in allen gängigen Schreibweisen,
IP-Adressen, beschriftete Kundennummern, Ausweis-/Pass-/Führerscheinnummern, Krankenversichertennummer,
Kfz-Kennzeichen, Steuernummer. Offen: unbeschriftete Kunden-/Auftragsnummern (firmenspezifische Muster).

Personen-Recall 0,84 -> 0,91 (21.11.2026) ohne Neutraining: Richternamen in Unterschriftenzeilen werden einzeln
nachgeprüft, weitere Richter einer Besetzung übernommen; Fehleranalyse in `docs/research/person-recall.md`.
Restfehler Personen: Nachnamen im Fließtext ohne Anrede/Rolle, Platzhalter („W ...“), als Firma typisierte Namen.

Messen: `python packages/core/scripts/ler_data.py eval --split test` und `court_data.py eval --split test`
(Ergebnisse in `datasets/*/eval_test*.json`). Grenzen: gemessen an veröffentlichten Urteilen, nicht an
Schriftsätzen/Mandantenmails; vor Produktion lokal an echten Beispielen messen (HANDOVER.md).

## 4. Entwicklungsumgebung

```bash
cd packages/core && python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
# spaCy-Modelle (Wheels von github.com/explosion/spacy-models/releases, Version 3.8.0)
python -m spacy download de_core_news_lg && python -m spacy download en_core_web_lg
git lfs pull                     # NER-Gewichte unter models/
pytest                           # erwartet: alle grün (384 passed, 2 skipped am 21.11.2026)

cd ../.. && npm install
npx tsc --noEmit -p .            # Typecheck Dashboard
npm run dev                      # Demo-Modus; live mit ANONYMIZER_API_URL=http://localhost:8080
```

Ohne `en_core_web_lg` schlagen 9 Tests fehl (Umgebung, kein Codefehler).

Trainieren (CPU, ~30–60 min):

```bash
python packages/core/scripts/finance_data.py eval   # Finanzdaten messen
python packages/core/scripts/ner_train.py --ler datasets/ler --courts datasets/courts \
  --synthetic 0 --germeval 0 --epochs 6 --out local/ner/models/<name>
# optional: --feedback feedback.jsonl  (Export aus Settings → Feedback)
```

Ein neues Modell nur übernehmen, wenn auf beiden Test-Splits besser (Recall-Personen darf nicht sinken).

## 5. Laufende Arbeit (Branches, nicht auf main)

| Branch | Inhalt | Stand |
|---|---|---|
| `claude/epic-thompson-ceb5ng` | Hauptentwicklungsbranch dieser Sitzung, entspricht main | – |
| `claude/peaceful-keller-md3af4-person-recall` | Personen-Recall (Unterschriftenzeilen, Besetzung), LER-Test Personen R 0,84 -> 0,91 | geprüft, nicht gemergt |
| `claude/peaceful-keller-md3af4-span-fix` | Aktenzeichen/Adressen enden an Zeile bzw. Satz; Finanz-Präzision -0,0004 | zur Entscheidung |

Abgeschlossen und gemergt: `claude/ner-org-recall`, `claude/outcome-experiment`, `claude/research-*`. Neue Arbeit erst nach Prüfung (Tests grün, Messung besser) nach main mergen.

## 6. Nächste Schritte (priorisiert)

1. **Firmen-Recall** (0,54 → Ziel ≥ 0,65 bei Präzision ≥ 0,90). Bisher: Regeln (Bindestrich-Rechtsformen, „Firma/Fa.“, e.K.)
   und `--org-repeat 2` halfen, synthetische Firmennamen nicht. Restfehler sind zu großen Teilen Verbandskürzel und Marken
   (oft keine personenbezogenen Daten). GLiNER als zweiter Detektor gemessen (optional, Standard aus): kein Gewinn,
   Präzision fällt, 25- bis 125-fache Latenz auf CPU (`docs/research/gliner-results.md`). Noch offen: GermEval 2014.
   Siehe `docs/research/org-ner.md` und `docs/research/org-ner-results.md`.
2. **Feedback-Schleife nutzen**: Korrekturen aus dem Chat sammeln (Settings → Feedback → Export) und mit `--feedback` nachtrainieren.
3. **Messung an echten Kanzleitexten** (lokal, berechtigte Person, ohne Cloud). Mess-Kit vorhanden:
   `docs/local-eval.md`, `packages/core/scripts/local_eval.py` (Vorannotation, Korrektur im Texteditor, `eval`, `report` nur mit Zahlen).
   Offen: Durchführung in einer Kanzlei.
4. **Ausgangsvorhersage: abgeschlossen, nicht weiterverfolgen.** Kündigungsschutzklagen, 3.226 Urteile,
   TF-IDF + logistische Regression: Macro-F1 0,44 im zeitlichen Split (3 Klassen; binär 0,62), Metadaten-Baselines
   0,29–0,36. Messbares, aber für ein Produkt zu schwaches Signal. Details und Reproduktion ohne Download:
   `datasets/outcome/README.md` (`outcome_experiment.py train --dir local/outcome`).
5. **Backend-Bereinigung: erledigt** (Branch `claude/peaceful-keller-md3af4-backend-cleanup`). Conversations, Prompts,
   Gateway (`/v1/chat/completions`) und MCP-Proxy (`/proxy/mcp`, `anonymizer-proxy`) entfernt (keine UI, weniger
   Angriffsfläche). Der Ergebnisfilter des Proxys lebt als `anonymizer/result_filter.py` weiter, weil der CSV-Playground
   ihn nutzt. Playground-Policy jetzt `ANONYMIZER_PLAYGROUND_POLICY` (alter Name `ANONYMIZER_CONVERSATIONS_POLICY` als
   Fallback). Vorhandene `conversations.db`/`prompts.db` werden nicht mehr gelesen und nicht gelöscht.

## 7. Regeln für die Weiterarbeit

- Keine echten Kunden-/Mandantendaten an Cloud-Modelle; Rohdaten aus Unternehmen nur unter `local/` (gitignoriert).
- Vor jedem Push: `pytest` und `npx tsc --noEmit -p .` grün; bei rotem Test nicht pushen.
- Neue Erkennungsregeln immer messen (`ler_data.py eval`, `court_data.py eval`) und mit Tests absichern.
- Lizenzen: LER CC BY 4.0, Gerichtsdaten ODbL 1.0 (Hinweise in `THIRD_PARTY_NOTICES.md` pflegen); CoNLL-2003 nicht verwenden.
- Modellgewichte über Git LFS (`models/**/model`).
- Netzwerk der Cloud-Umgebung "ANONYMIZER": zusätzlich freigegeben sind rechtsprechung-im-internet.de,
  de.openlegaldata.io (API drosselt stark; 429 respektieren), lfs.github.com, huggingface.co und dessen Download-Hosts.
