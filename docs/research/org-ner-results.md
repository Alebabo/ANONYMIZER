# Organisationen im deutschen juristischen NER: Ergebnisse vom 21.11.2026

Ziel: höherer Recall für Organisationen (Firmen) in der Pipeline Regeln + `de_core_news_lg` +
`models/de_legal_ner/ner`, ohne Präzision, Personen-Recall oder Recall auf `datasets/courts` zu verlieren.
Gerichte und Behörden zählen bewusst nicht als Organisation.

## Ergebnis

Übernommen: **neue ORG-Regeln + Modell-Lauf 3 (`--org-repeat 2`)**.

| LER test, komplette Pipeline (partial overlap) | Vorher | Nachher |
|---|---|---|
| Gesamt P / R / F1 | 0.916 / 0.714 / 0.803 | **0.923 / 0.751 / 0.828** |
| Personen P / R | 0.896 / 0.824 | 0.912 / 0.836 |
| Organisationen P / R | 0.877 / 0.451 | 0.883 / **0.538** |
| Orte P / R | 0.971 / 0.847 | 0.967 / 0.864 |
| PER/ORG/LOC-Treffer auf Gerichten, Normen, Rechtsprechung | 16 | 16 |
| Courts test: eingesetzte Werte gefunden (859) | 0.992 | **0.995** |
| Courts test: Organisationen | 7 / 9 | **9 / 9** |
| Courts test: Personen | 813 / 818 | 814 / 818 |

Übernahmekriterien (LER test ORG-Recall steigt, Gesamt-Präzision >= 0.90, Personen-Recall sinkt nicht,
Courts-Recall sinkt nicht): alle erfüllt.

## Alle Varianten

Pipeline = Regeln + NER. "Regeln alt" = Stand vor dieser Arbeit. Modellauswahl ausschließlich auf LER dev
(nach den Übernahmekriterien angewandt auf dev); Test-Zahlen der verworfenen Varianten wurden erst nach der
Auswahl gemessen und dienen nur der Dokumentation.

| Variante | Split | Gesamt P / R | PER P / R | ORG P / R | LOC P / R | Courts gesamt | Courts ORG |
|---|---|---|---|---|---|---|---|
| Regeln alt + Modell Lauf 2 (Baseline) | dev | 0.895 / 0.719 | 0.889 / 0.848 | 0.873 / 0.429 | 0.924 / 0.904 | | |
| | test | 0.916 / 0.714 | 0.896 / 0.824 | 0.877 / 0.451 | 0.971 / 0.847 | 0.992 | 7 / 9 |
| Regeln neu + Modell Lauf 2 | dev | 0.905 / 0.761 | 0.889 / 0.848 | 0.915 / 0.553 | 0.924 / 0.904 | | |
| | test | 0.920 / 0.738 | 0.896 / 0.824 | 0.899 / 0.526 | 0.971 / 0.847 | 0.994 | 9 / 9 |
| Regeln neu + `--org-augment 2` (T1) | dev | 0.906 / 0.760 | 0.896 / 0.845 | 0.884 / 0.557 | 0.944 / 0.899 | | |
| | test | 0.928 / 0.757 | 0.916 / 0.840 | 0.886 / 0.553 | 0.976 / 0.864 | 0.994 | 9 / 9 |
| Regeln neu + `--org-augment 4` (T2) | dev | 0.904 / 0.759 | 0.896 / 0.845 | 0.888 / 0.549 | 0.934 / 0.904 | | |
| | test | 0.921 / 0.749 | 0.908 / 0.824 | 0.883 / 0.538 | 0.967 / 0.872 | 0.993 | 9 / 9 |
| **Regeln neu + `--org-repeat 2` (T3, übernommen)** | dev | 0.904 / 0.766 | 0.894 / 0.851 | 0.901 / 0.564 | 0.924 / 0.904 | | |
| | test | 0.923 / 0.751 | 0.912 / 0.836 | 0.883 / 0.538 | 0.967 / 0.864 | 0.995 | 9 / 9 |
| Regeln neu + `--org-repeat 2 --org-augment 2` (T4) | dev | 0.909 / 0.766 | 0.899 / 0.845 | 0.896 / 0.568 | 0.940 / 0.910 | | |
| | test | 0.921 / 0.750 | 0.913 / 0.843 | 0.877 / 0.538 | 0.966 / 0.851 | 0.994 | 9 / 9 |

NER allein (Auswahlmetrik von `ner_train.py`, LER dev F1, beste Epoche): Lauf 2 0.760, T1 0.761, T2 0.760,
T3 0.770, T4 0.769.

Warum T3 und nicht T4 (höheres dev-F1) oder T1 (bestes Test-Ergebnis): T4 verliert auf dev Personen-Recall
(0.845 < 0.848) und verletzt damit das Kriterium schon auf dev; T1 bringt auf dev weniger ORG-Recall als T3.
Dass T1 auf Test vorne liegt, ist Rauschen: die Varianten trennen auf Test 3 bis 4 Organisationen
(253 im Test-Split), ein zweiter Seed würde die Reihenfolge vermutlich ändern.

## Was geholfen hat

1. **Regeln** (`packages/core/src/anonymizer/detect/recognizers.py`), der größte Teil des Gewinns
   (ORG-Recall dev 0.429 -> 0.553, test 0.451 -> 0.526, ORG-Präzision steigt sogar):
   - Rechtsform mit Bindestrich: "Hartmann-GmbH", "Becker-GbR", "X-EWIV", "Wójcik Kondensatoren-GmbH",
     "Ferrari-GmbH & atypisch Still", dazu "X-Gruppe", "X-Konzern", "X-Holding", "X-Werke"
     (`ORGANIZATION_HYPHEN`). Allein auf LER dev über 20 vorher verpasste Firmen.
   - "Firma X" / "Fa. X" ohne Rechtsform (`FIRM_CUE`, `organization_cue`): in LER train sind 67 von 69 solcher
     Stellen Organisationen.
   - Weitere Rechtsformen: e.K./e.Kfm./e.Kfr. (die beiden Courts-Fehler), GbR, EWIV, Aktiengesellschaft,
     Kommanditgesellschaft, B.V., N.V., S.A.; "& Co KG" ohne Punkt und "& Co. OHG" (vorher wurde "Co KG" als
     zweite Firma abgespalten); Großbuchstaben mit Diakritika am Wortanfang ("Çelik GmbH" wurde verpasst).
   - Schutz gegen Fehlalarme: generische Stämme ("Holding KG", "Vorrats-GmbH", "Komplementär-GmbH") und
     Gruppen-Komposita ("Facebook-Gruppe", "Alters-Gruppe") werden nicht markiert; "Das AG Köln" bleibt Gericht.
2. **`--org-repeat 2`** (LER-Dokumente mit Organisation zweimal zusätzlich): NER-dev-F1 0.760 -> 0.770,
   in der Pipeline zusätzlich ORG-Recall +0.01 auf dev und test, Personen-Recall test +0.012.

## Was nicht geholfen hat

- **`--org-augment N`** (Kopien von Firmen-Dokumenten, Firmennamen ersetzt durch synthetische Namen ohne
  Rechtsform: Kunstmarken wie "Novatronic", Kürzel wie "HKL", "Weber Logistik", "Hahn & Söhne"): allein kein
  messbarer Effekt auf dev (ORG-Recall 0.553 -> 0.557 bzw. 0.549), mit `--org-repeat` kombiniert auch nicht
  besser als `--org-repeat` allein. Grund: die verbleibenden Fehler sind kaum Firmen mit erkennbarer Form.
- **Propagation erkannter ORG-Namen** auf weitere Vorkommen im Dokument (analog zu Personen): +0.004 ORG-Recall
  auf dev, aber neue Fehlalarme in Entscheidungsnamen ("EuGH … – Actavis / Sanofi"). Verworfen, nicht committet.
- **Cues "Unternehmen X", "Arbeitgeberin X", "Beklagte zu 2), die X"**: in LER/Courts train fast nur Fehltreffer
  ("das Unternehmen Gewinne", "des Unternehmens Mit …") oder gar keine Firmen; nicht umgesetzt.

## Verbleibende ORG-Fehler (LER dev, 122 von 273)

| Art | Anzahl | Beispiele |
|---|---|---|
| Kürzel von Verbänden, Gewerkschaften, Institutionen | 40 | ZDS, MDK, VKA, GEW, DGB, ver.di, EU, PKK |
| Marken, Zitate in Anführungszeichen | 25 | Widerspruchsmarke NIVONA, „JOOP“, Wortmarke „fireslim“ |
| Ausgeschriebene Verbände, EU, Kirchen | 20 | Europäischen Union, Bundesverband des Schornsteinfegerhandwerks |
| Firmen/sonstige | 33 | meist bloßer Nachname als Firma: "Arbeitsverhältnis mit Kraus", "Organträgers Schmid" |
| Datensatz-Artefakte | 4 | "der Wójcik- weiter" (LER-Platzhalter "W-" ersetzt) |

Ob Verbände, Gewerkschaften und Marken überhaupt pseudonymisiert werden sollen, ist eine Produktfrage: sie sind
meist keine personenbezogenen Daten, zählen in LER aber als ORG. Nächste Hebel: Feedback aus dem Chat-Tab
(`--feedback`), ein zweiter ORG-Detektor (z. B. GLiNER `urchade/gliner_multi-v2.1`, Apache-2.0; Latenz auf CPU
messen), GermEval-2014-ORG als Rehearsal.

## Reproduzieren

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e "packages/core[dev]"
pip install https://github.com/explosion/spacy-models/releases/download/de_core_news_lg-3.8.0/de_core_news_lg-3.8.0-py3-none-any.whl
git lfs pull

# Training (je ca. 30 min auf einem CPU-Kern); nicht zwei Läufe gleichzeitig starten:
# ler_data.load entpackt nach datasets/ler/.ler_<split>.jsonl und löscht die Datei danach.
python packages/core/scripts/ner_train.py --ler datasets/ler --courts datasets/courts --synthetic 0 \
  --germeval 0 --epochs 6 --org-repeat 2 --out local/ner/models/org_rep2                    # T3, übernommen
#   T1: --org-augment 2   T2: --org-augment 4   T4: --org-repeat 2 --org-augment 2

# Messen (Pipeline):
ANONYMIZER_NER_MODEL_DE="de_core_news_lg+local/ner/models/org_rep2/ner" \
  python packages/core/scripts/ler_data.py eval --split dev --data <Kopie von datasets/ler>
ANONYMIZER_NER_MODEL_DE="de_core_news_lg+local/ner/models/org_rep2/ner" \
  python packages/core/scripts/court_data.py eval --split test --data <Kopie von datasets/courts>
```

Das Training ist mit Seed 24 reproduzierbar, aber nicht bitgenau über Plattformen; Unterschiede von ±0.01 in
den Recall-Werten liegen im Rauschen.

## Trainingsläufe vom 21.11.2026 (nach dem Zusammenführen von `feature/ner-v6`)

Ziel: Firmen-Recall (LER-Test 0.538 -> >= 0.65 bei P >= 0.90) und Personen im Fließtext ohne Anrede. Basis wie
Lauf 3 (`--ler datasets/ler --courts datasets/courts --synthetic 0`, Seed 24), Pipeline mit den Regeln nach dem
ner-v6-Merge. Auswahl auf LER dev, Bestätigung auf Test. Höchstens drei Läufe.

Neu in `ner_train.py`: `--germeval-public-o` setzt GermEval-ORG-Spannen auf Gerichte und Behörden
("Bundesverfassungsgericht", "Bundestag", "Bundeskartellamt") auf O, wie LER sie behandelt (GRT/INN). GermEval 2014
(CC BY 4.0) aus `huggingface.co/datasets/stefan-it/germeval14_no_wikipedia` (`original/NER-de-train.tsv`), lokal
unter `local/ner/public/germeval14/train.tsv`. MultiCoNER v2 (CC BY 4.0) wurde nicht verwendet: die Sätze sind
durchgehend klein geschrieben, und mit `de_legal_ner` behält die Pipeline klein geschriebene Treffer (Modell mit "+"),
das Risiko neuer Fehltreffer in Rechtstexten ist hoch, der Nutzen für Firmen mit Rechtsform gering.

| Lauf | Parameter | NER-dev-F1 (beste Epoche) | LER dev P / R | dev PER P / R | dev ORG P / R | Courts dev |
|---|---|---|---|---|---|---|
| Referenz `de_legal_ner` (Lauf 3) | `--org-repeat 2 --epochs 6` | 0.739* | 0.908 / 0.802 | 0.903 / 0.931 | 0.901 / 0.568 | 0.994 |
| R1 | `--germeval 4000 --germeval-public-o --org-repeat 2 --epochs 6`, nach Epoche 3 abgebrochen | 0.733 (E3) | 0.891 / 0.791 | 0.892 / 0.922 | 0.861 / 0.546 | 0.994 |
| R2 | `--org-repeat 3 --epochs 10` | **0.748** (E8) | **0.923** / 0.799 | 0.895 / 0.931 | 0.938 / 0.553 | 0.994 |
| R3 | `--germeval 4000 --germeval-public-o --org-repeat 3 --epochs 10` | 0.735 (E4) | 0.898 / 0.799 | 0.890 / 0.931 | 0.893 / 0.553 | 0.994 |

\* Die Auswahlmetrik von `ner_train.py` misst strikt mit den Regeln von `SpacyRecognizer`; seit ner-v6
(Anführungszeichen, Firmen nach Branchenwort, Nachname nach Vorname) liegt das Referenzmodell dort bei 0.739 statt
0.770. Die Zahlen sind daher nur innerhalb dieser Tabelle vergleichbar. R1 wurde nach Epoche 3 abgebrochen, weil die
Pipeline auf dev in allen Kennzahlen unter der Referenz lag; R3 (dieselben Daten, vollständig) bestätigt, dass
GermEval hier nicht hilft (Präzision sinkt, ORG-Recall auch).

Einziger Kandidat nach dev: R2 (Präzision höher, Personen-Recall gleich, F1 0.852 -> 0.857), obwohl der
ORG-Recall auf dev sinkt. Test:

| Test-Splits | Referenz | R2 |
|---|---|---|
| LER gesamt P / R / F1 | 0.923 / 0.782 / 0.847 | 0.932 / 0.791 / 0.855 |
| LER Personen P / R | 0.914 / 0.914 | 0.912 / 0.923 |
| LER Firmen P / R | 0.883 / 0.538 | 0.907 / 0.538 |
| LER Orte P / R | 0.967 / 0.864 | 0.981 / 0.881 |
| PER/ORG/LOC-Treffer auf Gerichten, Normen, Rechtsprechung | 18 | 14 |
| Courts eingesetzte Werte (859) | 0.995 (Personen 814/818) | 0.994 (813/818) |

**Nicht übernommen.** R2 ist auf LER-Test besser, auf Courts-Test aber um eine Person schlechter ("die Eheleute
Oldenburg", ein Nachname, der zugleich Stadt ist), und die Personen-Präzision auf LER sinkt leicht. Die Regel
"besser auf LER-Test und Courts-Test, weder Präzision noch Personen-Recall sinken" ist damit nicht erfüllt;
`models/de_legal_ner/` bleibt Lauf 3. Für den Firmen-Recall brachte keiner der Läufe etwas: mehr Gewicht auf
Firmen-Dokumenten verschiebt nur zwischen Präzision und Recall, die verbleibenden Fehler (Verbandskürzel, Marken,
Nachnamen als Firma) sind für das Modell ohne neue Daten nicht lernbar.

Reproduktion (je ca. 25 bis 60 min auf geteilten 4 CPU-Kernen):

```bash
python packages/core/scripts/ner_train.py --ler datasets/ler --courts datasets/courts --synthetic 0 --germeval 0 \
  --epochs 10 --org-repeat 3 --out local/ner/models/r2_rep3_e10                                         # R2
python packages/core/scripts/ner_train.py --ler datasets/ler --courts datasets/courts --synthetic 0 \
  --germeval 4000 --germeval-public-o --epochs 10 --org-repeat 3 --out local/ner/models/r3_ge4000_rep3_e10   # R3
# messen: Gewichte nach z. B. local/ner/de_legal_ner_r2/ner kopieren (Pfad muss "de_legal_ner" enthalten), dann
ANONYMIZER_NER_MODEL_DE="de_core_news_lg+local/ner/de_legal_ner_r2/ner" \
  python packages/core/scripts/ler_data.py eval --split dev --data <Kopie von datasets/ler>
```
