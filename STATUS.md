# Projektstand OpenAnonymizer

Stand: 25.11.2026. Übergabe für die Weiterarbeit, auch durch andere Coding-Agents (Codex, Claude Code).
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
| `packages/core/src/anonymizer/detect/` | Regeln (`recognizers.py`), Kontextsignale (`context.py`), spaCy-NER (`ner.py`), Firmenlisten/-muster (`orgs.py`), Wortlisten aus GermEval (`data/`) |
| `packages/core/src/anonymizer/policy/builtin/` | `banking-default`, `support-default`, **`legal-default`** |
| `packages/core/src/anonymizer/{ler,courts,feedback}.py` | Trainingsdaten (German LER, Gerichtsentscheidungen), Feedback-Speicher |
| `packages/core/scripts/` | `ler_data.py`, `court_data.py` (Daten bauen/messen), `ner_train.py` (Training), `ner_gold.py`, `ner_external.py` (syntriq/EasyOctopus Personen), `build_common_nouns.py`, `local_eval.py` (Mess-Kit echte Kanzleitexte, `docs/local-eval.md`) |
| `app/`, `components/`, `lib/` | Next.js-Dashboard: Tabs **Chat**, **Traces**, **CSV**; Settings: Policies, API Keys, Members, Feedback, Audit Logs |
| `models/cato-1.1/` | **Cato 1.1**: ein deutsches NER-Modell für Rechtstexte und Support-Mails/Chats, eigenständige spaCy-Pipeline, 43 MB (Git LFS), deutscher Standard. Ersetzt `de_legal_ner` und `de_custom_ner` (beide brauchten `de_core_news_lg`, 610 MB) |
| `datasets/ler/` | German LER (CC BY 4.0): Rohdaten `raw/`, Gold-JSONL, Auswertungen |
| `datasets/courts/` | 1.240 Entscheidungen von Open Legal Data (ODbL 1.0): Rohdaten `raw/`, Gold-JSONL mit synthetischen Werten |
| `datasets/finance/` | Drei synthetische Finanz-/Bank-/Support-Datensätze (Apache-2.0) zur Messung, `finance_data.py eval` |
| `datasets/public/` | Deutsche Teile von SmartData (CC BY 4.0, Firmen als eigener Typ), MAPA EUR-Lex (CC BY 4.0), E3-JSI und urchade (synthetisch, MIT/Apache-2.0): Messung `public_pii.py eval`, Training `ner_train.py --public` |
| `docs/research/` | Recherchen: `outcome-prediction.md`, `org-ner.md`, `org-ner-results.md`, `person-recall.md`, `gliner-results.md`, `newmean-pii.md`, `unified-ner-md.md` |
| `datasets/outcome/` | Machbarkeitsexperiment Ausgangsvorhersage Kündigungsschutz (3.226 Urteile, ODbL), `outcome_experiment.py` |

## 3. Aktuelle Qualität (Test-Splits, komplette Pipeline)

Seit 25.11.2026 ist Cato 1.1 das deutsche Standardmodell. Werte gegen die früheren Spezialmodelle:
[models/cato-1.1/README.md](models/cato-1.1/README.md). Cato liegt beim Recall 0,3 bis 1,6 Punkte (LER, Gerichte, syntriq),
auf Gretel 4,7 Punkte unter dem jeweils besten Spezialmodell; bewusst übernommen für ein Modell statt zwei und
43 statt 616 MB.

Die Tabelle unten stammt noch vom früheren Rechtsmodell `de_legal_ner` (`de_core_news_lg+models/de_legal_ner/ner`):

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
0,586, Gretel 0,673 der Werte (vorher 0,808 / 0,398 / 0,636); Präzisions-Untergrenze 0,549 / 0,702 / 0,379.
Gretel stieg mit den Firmenregeln aus `feature/ner-v6` (0,655 -> 0,673, Firmen 0,649 -> 0,709, siehe unten). Neu erkannt: Telefon in allen gängigen Schreibweisen,
IP-Adressen, beschriftete Kundennummern, Ausweis-/Pass-/Führerscheinnummern, Krankenversichertennummer,
Kfz-Kennzeichen, Steuernummer. Offen: unbeschriftete Kunden-/Auftragsnummern (firmenspezifische Muster).

Personen-Recall 0,84 -> 0,91 (21.11.2026) ohne Neutraining: Richternamen in Unterschriftenzeilen werden einzeln
nachgeprüft, weitere Richter einer Besetzung übernommen; Fehleranalyse in `docs/research/person-recall.md`.
Restfehler Personen: Nachnamen im Fließtext ohne Anrede/Rolle, Platzhalter („W ...“), als Firma typisierte Namen.

Stand nach dem Zusammenführen am 21.11.2026 (Branch `claude/peaceful-keller-md3af4`), Test-Splits:

| Schritt | LER P / R | LER Personen P / R | LER Firmen P / R | Courts gesamt (Personen) | Finanz geschützt / P-Untergrenze (gretel, syntriq, EasyOctopus) |
|---|---|---|---|---|---|
| Ausgangsstand (person-recall, messkit, backend-cleanup) | 0,923 / 0,782 | 0,914 / 0,914 | 0,883 / 0,538 | 0,995 (814/818) | 0,655 / 0,3717, 0,905 / 0,5495, 0,586 / 0,7018 |
| + span-fix | unverändert | unverändert | unverändert | unverändert | 0,655 / 0,3717, 0,905 / 0,5495, 0,586 / 0,7018 |
| + ner-v6 unverändert | 0,912 / 0,782 | 0,914 / 0,914 | 0,840 / 0,538 | 0,995 | 0,673 / 0,379, 0,905 / 0,5455, 0,586 / 0,702 |
| + ner-v6 angepasst (übernommen) | 0,923 / 0,782 | 0,914 / 0,914 | 0,883 / 0,538 | 0,995 (814/818) | 0,673 / 0,3791, 0,905 / 0,5492, 0,586 / 0,7018 |

Anpassungen an ner-v6: Gerichte und Behörden (Staatsanwaltschaft, Amts-/Landgericht, Finanzamt, Jobcenter,
Polizeipräsidium; BaFin, Bundeszentralamt für Steuern, Deutsche Rentenversicherung, BKA) sind keine Firmen
(sie brachten auf LER-Test 8 Fehltreffer), „Schufa“ ist nicht mehr in der Liste bekannter Firmen (81 Treffer auf den
Finanzdaten, keiner davon ein Wert), Titel beenden einen Firmennamen nach Branchenwort („Zahnarztpraxis Dr. Gude“
behält die Person), „Holding KG“ ist eine Rolle. Die verbleibende syntriq-Differenz (-0,0003) sind korrekt erkannte,
in syntriq nicht annotierte Firmen (Hotels, Praxen, Kanzleien); ohne Firmentreffer steigt die syntriq-Präzision
0,5694 -> 0,5727. LER strikt (exakte Grenzen) sinkt bei Firmen 126 -> 122 Treffer, weil ner-v6 Anführungszeichen
nicht mehr zum Namen zählt (LER annotiert „Gotham“ mit Zeichen); partiell unverändert.

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
pytest                           # erwartet: alle grün (388 passed am 22.11.2026)

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
# optional: --germeval N [--germeval-public-o]  (GermEval 2014 unter local/ner/public/germeval14/train.tsv,
#           z. B. huggingface.co/datasets/stefan-it/germeval14_no_wikipedia, original/NER-de-train.tsv)
# Zum Messen den Modellordner so benennen, dass der Pfad "cato" (oder "de_legal_ner") enthält:
# die Einzelwort-Prüfung für Unterschriftenzeilen läuft nur mit diesem Namen.
# Danach verkleinern: ner_compact.py <out> models/cato-x.y --name cato --version x.y.0 --check datasets/ler/ler_dev.jsonl.gz
```

Ein neues Modell nur übernehmen, wenn auf beiden Test-Splits besser (Recall-Personen darf nicht sinken).

## 5. Laufende Arbeit (Branches)

25.11.2026: `feature/newmean-detector` in `main` zusammengeführt (Cato 1.1, öffentliche PII-Datensätze, optionaler
newmean-Detektor, `ner_compact.py`, `ner_prune_base.py`). Die Absätze darunter sind älter.

`main` steht auf `e2a3c4e` und enthält alles aus der Sitzung vom 21./22.11.2026. Keine offenen Arbeitsbranches.

Auf main zusammengeführt (Branches können gelöscht werden): `claude/peaceful-keller-md3af4` (Sammelbranch) mit
`-person-recall`, `-span-fix`, `-messkit`, `-backend-cleanup`, `-gliner` sowie `feature/ner-v6` (angepasst, siehe
Abschnitt 3); früher schon `claude/epic-thompson-ceb5ng`, `claude/ner-org-recall`, `claude/outcome-experiment`,
`claude/research-*`, `feature/ner-training`.

Veraltet (vor dem Neuaufsetzen von main am 19.11.2026, keine gemeinsame Historie mit main): `claude/brave-hawking-t1behw`,
`claude/cato-privacy-infrastructure-ppysem`, `claude/eager-faraday-pm1krh`, `claude/fervent-goldberg-6gtxv2`,
`claude/keen-brahmagupta-jpiycw`, `claude/keen-wright-nz195h`, `claude/new-session-5566vm`,
`claude/simplify-nav-playground`, `claude/sweet-curie-733nyb`. Vor dem Löschen als Tag `archive/<name>` sichern.
Löschen geht nicht aus der Cloud-Umgebung (Push-Verbot außer auf den Sitzungsbranch), nur lokal mit `git push origin --delete`.

CI (`.github/workflows/ci.yml`) läuft seit 21.11.2026 nur auf `main`, bei Pull Requests und manuell
(`workflow_dispatch`), nicht mehr bei jedem Push auf Arbeitsbranches. Arbeitsbranches deshalb vor dem Merge lokal prüfen
(`pytest`, `npx tsc --noEmit -p .`, Messungen).

Bekannte Stolperstellen:
- `finance_data.py eval` überspringt Gretel stillschweigend, wenn `pyarrow` oder die Gretel-Daten fehlen
  (`finance_data.py download`), und überschreibt `datasets/finance/eval.json` dann ohne Gretel. Vor dem Committen prüfen.
- `ler_data.py eval` schreibt je nach Konfiguration `eval_test.json` oder `eval_test_de_legal_ner.json`; nur die Datei
  der gemessenen Konfiguration committen.
- In git-Worktrees zeigt `pip install -e` auf das Hauptverzeichnis: `PYTHONPATH=<worktree>/packages/core/src` setzen.

## 6. Nächste Schritte (priorisiert)

1. **Messung an echten Kanzleitexten** (lokal, berechtigte Person, ohne Cloud). Mess-Kit vorhanden:
   `docs/local-eval.md`, `packages/core/scripts/local_eval.py` (Vorannotation, Korrektur im Texteditor, `eval`, `report` nur mit Zahlen).
   Am 22.11.2026 mit synthetischen Dokumenten (DOCX, PDF, Mails) komplett durchgespielt und ergänzt: `selbsttest` für die
   IT (synthetische Gold-Daten in `examples/local-eval/`, prüft NER, Rechtsmodell, Recall), Anrede/Titel werden vor dem
   Messen abgeschnitten (sonst „teilweise“ statt „vollständig“ verdeckt), Warnung bei fehlerhafter PDF-Textebene (■, �),
   Einrichtungsabschnitt in der Anleitung.
   Offen: Durchführung in einer Kanzlei. Wichtigster nächster Schritt: alle Zahlen oben stammen aus veröffentlichten Urteilen.
2. **Firmen-Recall** (0,54 → Ziel ≥ 0,65 bei Präzision ≥ 0,90). Bisher: Regeln (Bindestrich-Rechtsformen, „Firma/Fa.“, e.K.)
   und `--org-repeat 2` halfen, synthetische Firmennamen nicht. Am 21.11.2026 drei weitere Trainingsläufe (GermEval 2014
   als Rehearsal, `--org-repeat 3`, 10 Epochen): keiner hob den Firmen-Recall (LER-Test 0,538 unverändert), Modell nicht
   getauscht; Details in `docs/research/org-ner-results.md`. Das Modell ist hier ausgereizt; Restfehler sind
   Verbandskürzel, Marken und bloße Nachnamen als Firma. GLiNER als zweiter Detektor gemessen (optional, Standard aus): kein Gewinn,
   Präzision fällt, 25- bis 125-fache Latenz auf CPU (`docs/research/gliner-results.md`). Nächste Hebel: Feedback aus echten Texten, Produktentscheidung, ob Verbände/Marken überhaupt pseudonymisiert werden.
2a. **Fehler aus dem Selbsttest** (synthetisch, `examples/local-eval/`; einzeln prüfen, jeweils messen):
   Adresse „Am Rosengarten 7, 51061 Köln“ nach Geburtsdatum nicht erkannt (nur „Köln“ als Ort); Personentreffer
   „Wollenweber\nRechtsanwältin“ reicht über den Zeilenumbruch in die Berufsbezeichnung; eigenes Aktenzeichen ohne
   Kontextwort („Aktenvermerk WO-2026/0388“) verpasst; Anschrift des Gerichts unter „Landgericht Köln“ als Adresse
   markiert; kleingeschriebene Mail („hallo frau wollenweber“, „gruß mehmet aydoğan“) ohne einen einzigen Treffer.
   Auf diesen vier Dokumenten verdeckt das Standardmodell mehr Personen als das Rechtsmodell (0,83 gegenüber 0,79),
   allein wegen der Mails; Stichprobe zu klein für eine Entscheidung.
3. **Personen im Fließtext ohne Anrede**: Lauf `--org-repeat 3 --epochs 10` (R2) brachte auf LER-Test Personen-Recall
   0,914 -> 0,923 und Gesamtpräzision 0,923 -> 0,932 (Personen-Präzision 0,914 -> 0,912), verlor aber auf Courts-Test eine Person (813 statt 814/818) und wurde
   deshalb nicht übernommen. Kandidat für einen zweiten Seed oder für die Kombination mit Feedback-Daten.
4. **Feedback-Schleife nutzen**: Korrekturen aus dem Chat sammeln (Settings → Feedback → Export) und mit `--feedback` nachtrainieren.
5. **Ausgangsvorhersage: abgeschlossen, nicht weiterverfolgen.** Kündigungsschutzklagen, 3.226 Urteile,
   TF-IDF + logistische Regression: Macro-F1 0,44 im zeitlichen Split (3 Klassen; binär 0,62), Metadaten-Baselines
   0,29–0,36. Messbares, aber für ein Produkt zu schwaches Signal. Details und Reproduktion ohne Download:
   `datasets/outcome/README.md` (`outcome_experiment.py train --dir local/outcome`).
6. **Backend-Bereinigung: erledigt** (auf main). Conversations, Prompts,
   Gateway (`/v1/chat/completions`) und MCP-Proxy (`/proxy/mcp`, `anonymizer-proxy`) entfernt (keine UI, weniger
   Angriffsfläche). Der Ergebnisfilter des Proxys lebt als `anonymizer/result_filter.py` weiter, weil der CSV-Playground
   ihn nutzt. Playground-Policy jetzt `ANONYMIZER_PLAYGROUND_POLICY` (alter Name `ANONYMIZER_CONVERSATIONS_POLICY` als
   Fallback). Vorhandene `conversations.db`/`prompts.db` werden nicht mehr gelesen und nicht gelöscht.

## 7. Regeln für die Weiterarbeit

- Keine echten Kunden-/Mandantendaten an Cloud-Modelle; Rohdaten aus Unternehmen nur unter `local/` (gitignoriert).
- Vor jedem Push: `pytest` und `npx tsc --noEmit -p .` grün; bei rotem Test nicht pushen.
- Neue Erkennungsregeln immer messen (`ler_data.py eval`, `court_data.py eval`) und mit Tests absichern.
- Lizenzen: LER CC BY 4.0, Gerichtsdaten ODbL 1.0, GermEval 2014 und MultiCoNER v2 CC BY 4.0 (Hinweise in `THIRD_PARTY_NOTICES.md` pflegen); CoNLL-2003 nicht verwenden.
- Modellgewichte über Git LFS (`models/**/model`).
- Netzwerk der Cloud-Umgebung "ANONYMIZER": zusätzlich freigegeben sind rechtsprechung-im-internet.de,
  de.openlegaldata.io (API drosselt stark; 429 respektieren), lfs.github.com, huggingface.co und dessen Download-Hosts.
