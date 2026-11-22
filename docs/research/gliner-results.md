# GLiNER als zweiter Detektor: Ergebnisse vom 21.11.2026

Frage: Hebt GLiNER (Zero-Shot-Span-NER) als zusätzlicher Detektor neben Regeln + `de_core_news_lg` +
`models/de_legal_ner/ner` den Firmen-Recall (LER test 0,54, Ziel ≥ 0,65 bei Präzision ≥ 0,90), ohne Präzision
oder Personen-Recall zu verlieren?

**Antwort: nein.** Keine Variante erfüllt die Abnahmekriterien aus AGENTS.md. Die Integration bleibt als optionale,
standardmäßig **ausgeschaltete** Funktion im Code (für eigene Messungen, z. B. an Support-Texten), wird aber nicht
aktiviert.

## Ergebnis in Kürze

- Auf LER bringt GLiNER zusätzliche Firmen nur zusammen mit sehr vielen Fehltreffern. Unter den Treffern, die GLiNER
  zusätzlich zu Regeln und spaCy liefert, sind auf LER dev bei Schwelle 0,5 nur 40 echte Organisationen gegenüber
  753 Fehltreffern; in keinem Konfidenzbereich liegt der Anteil echter Organisationen über ca. 20 %.
- Hauptursache: GLiNERs Begriff „organization“ umfasst Behörden, Ministerien, Ämter, Senate, Kassen und Kliniken
  („Deutsches Patent- und Markenamt“, „Bundesministerium der Verteidigung“, „Familienkasse“, „Senat“, „Bund“).
  In LER (und im Produkt) sind das öffentliche Stellen (INN), keine personenbezogenen Daten.
- Hohe Schwellen (0,9–0,95) halten die Präzision einigermaßen, bringen dann aber praktisch keinen Recall mehr
  (ORG-Recall test 0,538 → 0,542 bei ORG-Präzision 0,883 → 0,840).
- Gerichtsentscheidungen (`datasets/courts`): keine Veränderung (0,995; ORG 9/9 schon ohne GLiNER).
- Finanz-/Supporttexte: deutlicher Recall-Gewinn bei Union PER+ORG+LOC (Gretel 0,655 → 0,823), aber die
  Präzisions-Untergrenze sinkt auf syntriq und EasyOctopus. Einziger Bereich, in dem sich ein weiterer Blick lohnt.
- Latenz auf CPU: GLiNER-Base kostet ein Vielfaches der bisherigen Pipeline (Tabelle unten).

## Modelle und Lizenzen

Nur Modelle mit kommerziell nutzbarer Lizenz; Angaben aus den Modellkarten auf huggingface.co (abgerufen 21.11.2026).

| Modell | Lizenz (Modell) | Basis-Encoder (Lizenz) | Trainingsdaten (Lizenz) | Gemessen |
|---|---|---|---|---|
| `urchade/gliner_multi-v2.1` | Apache-2.0 | `microsoft/mdeberta-v3-base` (MIT), ca. 280 M Parameter | `urchade/pile-mistral-v0.1` (Apache-2.0, mit Mistral erzeugt) | LER dev+test, Courts, Finance |
| `urchade/gliner_multi_pii-v1` | Apache-2.0 | mdeberta-v3-base (MIT) | Feinjustierung von multi-v2.1 auf `urchade/synthetic-pii-ner-mistral-v1` (Apache-2.0) | LER dev (Screening) |
| `knowledgator/gliner-x-small` | Apache-2.0 | `google/mt5-small` (Apache-2.0) | `knowledgator/gliner-multilingual-synthetic` (LLM-annotiertes FineWeb-2; Lizenz auf der Datensatzkarte **nicht angegeben**) | LER dev+test, Courts, Finance |
| `urchade/gliner_multi` (v0) | **CC BY-NC 4.0** | – | – | ausgeschlossen (nicht kommerziell) |

Nicht gemessen: `knowledgator/gliner-x-base/-large` (Apache-2.0; größer und langsamer als x-small, das schon
keinen Gewinn zeigte), englische Modelle (`gliner_small/medium-v2.1`, `gliner-pii-base-v1.0`,
`gliner-multitask-large-v0.5`, `modern-gliner-bi-base`; alle Apache-2.0, aber nur Englisch trainiert).

Hinweise: `gliner-x-*` braucht zusätzlich `stanza` (Apache-2.0) und `langdetect` (Apache-2.0) als Wortzerleger;
Stanza lädt beim ersten Aufruf eigene Ressourcen nach. Das Paket `gliner` (Apache-2.0) zieht PyTorch nach
(unter Linux standardmäßig mit CUDA-Abhängigkeiten, mehrere GB; für CPU vorher `torch` vom CPU-Index installieren).
Modellgewichte werden nicht im Repo abgelegt, sondern beim ersten Aufruf von huggingface.co geladen (oder lokaler
Pfad). Für den Betrieb ohne Internet: Modell vorab herunterladen und `ANONYMIZER_GLINER_MODEL` auf den Pfad setzen.

## Integration (optional, Standard aus)

`packages/core/src/anonymizer/detect/gliner_ner.py`, eingebunden in `detect/engine.py`.

| Einstellung | Umgebungsvariable | Standard |
|---|---|---|
| `DetectorConfig.gliner_model` | `ANONYMIZER_GLINER_MODEL` (HF-Id oder Pfad) | leer = aus |
| `DetectorConfig.gliner_types` | `ANONYMIZER_GLINER_TYPES` (`organization` oder z. B. `person,organization,location`) | `organization` |
| `DetectorConfig.gliner_threshold` | `ANONYMIZER_GLINER_THRESHOLD` | 0,5 |

Installation: `pip install "anonymizer-core[gliner]"`. Fehlt das Paket oder das Modell, erscheint in `scan()` eine
Warnung „GLiNER disabled: …“, die Erkennung läuft wie bisher weiter.

Verhalten:
- Prompt-Labels englisch („person“, „organization“, „company“, „location“); es werden immer alle Labels abgefragt,
  auch wenn nur Organisationen übernommen werden (sonst würden Nachnamen mangels Alternative als Firma gemeldet).
- Text wird an Satzgrenzen in Stücke von höchstens 200 Wörtern geteilt (GLiNER-Fenster 384 Tokens).
- GLiNER-Treffer laufen durch dieselben Filter wie spaCy-Treffer: `authority_type` (Gerichte/Behörden),
  `clean_entity` mit den NER-Stoppwörtern. Bei Überlappung gewinnen Regeln (Gerichte, Normen, Zitate,
  Aktenzeichen …) immer, danach spaCy; GLiNER ergänzt nur Spannen, die sonst niemand gefunden hat
  (`STATISTICAL_RECOGNIZERS` mit Rangstufe in `engine._rank`).
- Detektionen tragen `recognizer="gliner"` und die Attribute `score` und `label`.

## Messaufbau

- Pipeline-Stand: `claude/peaceful-keller-md3af4` mit Personen-Recall-Verbesserungen (Commit `8ff003a`),
  `ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_legal_ner/ner"` für LER und Courts, Finance ohne Rechtsmodell
  (wie `finance_data.py eval`).
- Gemessen mit den unveränderten Funktionen `ler_data.py eval`, `court_data.py eval`, `finance_data.py eval`.
  Die GLiNER-Rohvorhersagen (Schwelle 0,25) wurden einmal pro Modell und Textstück berechnet und zwischengespeichert;
  eine Schwelle t liefert damit exakt dieselben Spannen wie ein Lauf mit Schwelle t (greedy Dekodierung nach Score).
- Tuning ausschließlich auf LER dev; Test, Courts und Finance nur für die auf dev sinnvollen Varianten.
- Strategien: (a) GLiNER nur für ORG zusätzlich, (b) GLiNER für PER+ORG+LOC als Union mit Standardschwelle 0,5,
  (c) Union mit Schwellen-Sweep 0,3–0,95.

## LER dev (Tuning)

Partial overlap, P / R. Baseline = aktuelle Pipeline ohne GLiNER.

| Variante | Gesamt P / R | PER P / R | ORG P / R | LOC P / R | FP auf Gerichten/Normen/Zitaten |
|---|---|---|---|---|---|
| Baseline | 0,908 / 0,801 | 0,903 / 0,931 | 0,901 / 0,564 | 0,924 / 0,904 | 23 |
| multi-v2.1, (a) ORG, 0,5 | 0,455 / 0,847 | 0,903 / 0,931 | 0,198 / 0,700 | 0,924 / 0,904 | 294 |
| multi-v2.1, (a) ORG, 0,7 | 0,672 / 0,829 | 0,903 / 0,931 | 0,389 / 0,648 | 0,924 / 0,904 | 166 |
| multi-v2.1, (a) ORG, 0,8 | 0,779 / 0,817 | 0,903 / 0,931 | 0,548 / 0,612 | 0,924 / 0,904 | 95 |
| multi-v2.1, (a) ORG, 0,85 | 0,832 / 0,811 | 0,903 / 0,931 | 0,661 / 0,593 | 0,924 / 0,904 | 69 |
| multi-v2.1, (a) ORG, 0,9 | 0,871 / 0,805 | 0,903 / 0,931 | 0,770 / 0,575 | 0,924 / 0,904 | 46 |
| multi-v2.1, (a) ORG, 0,95 | 0,900 / 0,803 | 0,903 / 0,931 | 0,872 / 0,571 | 0,924 / 0,904 | 29 |
| multi-v2.1, (b) Union, 0,5 | 0,261 / 0,865 | 0,237 / 0,960 | 0,198 / 0,700 | 0,568 / 0,931 | 370 |
| multi-v2.1, (c) Union, 0,9 | 0,829 / 0,808 | 0,819 / 0,937 | 0,770 / 0,575 | 0,914 / 0,910 | 54 |
| multi-v2.1, (c) Union, 0,95 | 0,900 / 0,805 | 0,903 / 0,934 | 0,872 / 0,571 | 0,924 / 0,904 | 29 |
| multi_pii-v1, (a) ORG, 0,5 | 0,426 / 0,836 | 0,903 / 0,931 | 0,174 / 0,667 | 0,924 / 0,904 | 214 |
| multi_pii-v1, (a) ORG, 0,9 | 0,812 / 0,807 | 0,903 / 0,931 | 0,609 / 0,582 | 0,924 / 0,904 | 67 |
| multi_pii-v1, (a) ORG, 0,95 | 0,873 / 0,801 | 0,903 / 0,931 | 0,774 / 0,564 | 0,924 / 0,904 | 36 |
| multi_pii-v1, (c) Union, 0,95 | 0,836 / 0,808 | 0,833 / 0,945 | 0,774 / 0,564 | 0,910 / 0,910 | 39 |
| x-small, (a) ORG, 0,5 | 0,342 / 0,847 | 0,903 / 0,931 | 0,131 / 0,700 | 0,924 / 0,904 | 387 |
| x-small, (a) ORG, 0,7 | 0,651 / 0,816 | 0,903 / 0,931 | 0,352 / 0,608 | 0,924 / 0,904 | 158 |
| x-small, (a) ORG, 0,75 | 0,769 / 0,813 | 0,903 / 0,931 | 0,524 / 0,601 | 0,924 / 0,904 | 101 |
| x-small, (a) ORG, 0,8 | 0,852 / 0,808 | 0,903 / 0,931 | 0,711 / 0,586 | 0,924 / 0,904 | 50 |
| x-small, (a) ORG, 0,85 | 0,900 / 0,801 | 0,903 / 0,931 | 0,870 / 0,564 | 0,924 / 0,904 | 27 |
| x-small, (a) ORG, ≥ 0,9 | = Baseline (keine Treffer über 0,9) | | | | 23 |
| x-small, (b) Union, 0,5 | 0,273 / 0,868 | 0,424 / 0,960 | 0,131 / 0,700 | 0,545 / 0,941 | 479 |
| x-small, (c) Union, 0,8 | 0,837 / 0,815 | 0,877 / 0,940 | 0,711 / 0,586 | 0,910 / 0,915 | 63 |
| x-small, (c) Union, 0,85 | 0,897 / 0,803 | 0,896 / 0,937 | 0,870 / 0,564 | 0,924 / 0,904 | 30 |

Weitere Schwellen (multi-v2.1, 0,3 und 0,4) lagen noch schlechter (ORG-Präzision 0,125 / 0,157).

Kein Punkt der Sweeps erreicht ORG-Recall ≥ 0,65 bei Gesamt-Präzision ≥ 0,90. Jede Variante, die ORG-Recall
messbar hebt, senkt die Gesamt-Präzision unter 0,90 und die ORG-Präzision deutlich; die Union-Varianten senken
zusätzlich die Personen-Präzision. Auswahl für den Test-Split daher nur zur Dokumentation: (a) und (b) mit Standard-
schwelle 0,5, (a) und (c) mit der jeweils kleinsten Schwelle, bei der die Gesamt-Präzision auf dev noch ≥ 0,90 ist
(multi-v2.1: 0,95), sowie x-small 0,8 als bester ORG-Recall-Kompromiss.

### Welche Fehltreffer (multi-v2.1, ORG, Schwelle 0,7, LER dev)

24 zusätzliche richtige Organisationen (z. B. „Europäischen Union“, „Deutsche Gewerkschaftsbund“,
„Bundesverband des Schornsteinfegerhandwerks“, „Eli Lilly“, „Paul-Ehrlich-Institut“), dagegen 260 Fehltreffer:
116 auf Text ohne Gold-Label, 88 auf öffentlichen Institutionen (INN), 22 auf Rechtsprechungszitaten, 12 auf
Verträgen, 9 auf EU-Normen, Rest auf Gerichten/Gesetzen/Literatur. Häufigste: „Deutschen Patent- und Markenamts“
(19), „Bundesministerium der Verteidigung“ (10), „TV-Ärzte Hessen“ (7), „Senat“ (5), „Bund“ (5), „Familienkasse“,
„Bundesregierung“, „Patentamt“, „Luftwaffe“, „Finanzamt“, „Apotheke“, „Krankenkassen“, „BFH-Urteil“. Mit dem Label
„company“ allein (statt „organization“) sinkt die Zahl der Fehltreffer, aber auch der Gewinn: 9 richtige gegenüber
52 falschen bei Schwelle 0,5. Eine Stoppliste für Behörden würde einen Teil abfangen, die 116 Fehltreffer auf
unmarkiertem Text (Gattungswörter wie „Hersteller“, „Kundenbetrieb“, „Personalabteilung“) aber nicht.

## Test-Splits (final)

### LER test

| Variante | Gesamt P / R / F1 | PER P / R | ORG P / R | LOC P / R | FP öffentl. |
|---|---|---|---|---|---|
| **Baseline** | **0,923 / 0,782 / 0,847** | 0,914 / 0,914 | 0,883 / 0,538 | 0,967 / 0,864 | 18 |
| multi-v2.1, (a) ORG, 0,5 | 0,459 / 0,823 / 0,589 | 0,914 / 0,914 | 0,183 / 0,668 | 0,967 / 0,864 | 349 |
| multi-v2.1, (a) ORG, 0,9 | 0,862 / 0,789 / 0,824 | 0,914 / 0,914 | 0,676 / 0,561 | 0,967 / 0,864 | 62 |
| multi-v2.1, (a) ORG, 0,95 | 0,912 / 0,783 / 0,843 | 0,914 / 0,914 | 0,840 / 0,542 | 0,967 / 0,864 | 24 |
| multi-v2.1, (b) Union, 0,5 | 0,259 / 0,862 / 0,398 | 0,217 / 0,954 | 0,183 / 0,668 | 0,617 / 0,945 | 440 |
| multi-v2.1, (c) Union, 0,95 | 0,905 / 0,783 / 0,840 | 0,897 / 0,914 | 0,840 / 0,542 | 0,967 / 0,864 | 27 |
| x-small, (a) ORG, 0,8 | 0,857 / 0,791 / 0,823 | 0,914 / 0,914 | 0,665 / 0,565 | 0,967 / 0,864 | 57 |
| x-small, (c) Union, 0,8 | 0,832 / 0,799 / 0,815 | 0,874 / 0,920 | 0,665 / 0,565 | 0,929 / 0,885 | 77 |

Das Ziel ORG-Recall ≥ 0,65 erreicht nur Schwelle 0,5 (0,668), dann aber mit ORG-Präzision 0,18 und Gesamt-Präzision
0,46. Die beste Variante nach F1 bleibt die Baseline.

### Gerichtsentscheidungen (courts test, eingesetzte Werte gefunden)

| Variante | gesamt | PER | ORG | LOC |
|---|---|---|---|---|
| Baseline | 0,995 | 814/818 | 9/9 | 13/13 |
| multi-v2.1, (a) ORG, 0,5 / 0,95 | 0,995 | 814/818 | 9/9 | 13/13 |
| multi-v2.1, (b) Union, 0,5 | 0,997 | 815/818 | 9/9 | 13/13 |
| multi-v2.1, (c) Union, 0,95 | 0,995 | 814/818 | 9/9 | 13/13 |
| x-small, (a) ORG / (c) Union, 0,8 | 0,995 | 814/818 | 9/9 | 13/13 |

Courts misst nur Recall auf eingesetzten Werten; Fehltreffer werden hier nicht gezählt (siehe LER).

### Finanz-/Supporttexte (`finance_data.py eval`, ohne Rechtsmodell)

Geschützte Werte (Recall) / Präzisions-Untergrenze (Anteil der Detektionen, die einen Gold-Wert berühren).

| Variante | Gretel | syntriq | EasyOctopus |
|---|---|---|---|
| Baseline | 0,655 / 0,372 | 0,905 / 0,550 | 0,586 / 0,702 |
| multi-v2.1, (a) ORG, 0,5 | 0,720 / 0,375 | 0,905 / 0,534 | 0,586 / 0,651 |
| multi-v2.1, (a) ORG, 0,95 | 0,658 / 0,373 | 0,905 / 0,550 | 0,586 / 0,702 |
| multi-v2.1, (b) Union, 0,5 | **0,823** / 0,370 | **0,925** / 0,526 | **0,637** / 0,622 |
| multi-v2.1, (c) Union, 0,95 | 0,694 / 0,379 | 0,911 / 0,546 | 0,633 / 0,711 |
| x-small, (a) ORG, 0,8 | 0,666 / 0,374 | 0,905 / 0,549 | 0,586 / 0,702 |
| x-small, (c) Union, 0,8 | 0,681 / 0,378 | 0,911 / 0,549 | 0,621 / 0,714 |

Auf den synthetischen Finanztexten hilft GLiNER beim Recall deutlich, vor allem bei Personen- und Firmennamen in
Fließtext ohne Rechtsform. Die Präzisions-Untergrenze sinkt aber bei (b) auf syntriq und EasyOctopus und bei (c)
leicht auf syntriq (x-small Union 0,8: syntriq 0,550 → 0,549, sonst steigend, aber auf LER deutlich schlechter); die Kriterien sind damit auch hier nicht erfüllt. Die Untergrenze ist grob (nicht annotierte,
aber schützenswerte Werte zählen als Fehltreffer); für eine Entscheidung im Support-Bereich müsste an echten,
lokal annotierten Beispielen gemessen werden.

## Laufzeit (CPU)

Komplette `Detector.scan()`-Pipeline, GLiNER nur für ORG (Laufzeit hängt kaum von Typen/Schwelle ab).
Stichprobe: 60 zufällige LER-test-Dokumente (Ø 1.292 Zeichen) und 10 Entscheidungen aus courts test (auf 8.000
Zeichen gekürzt). CPU mit 4 Kernen, die mit einem parallel trainierenden Prozess geteilt waren; Zahlen daher eher
obere Werte, Verhältnisse belastbar.

| Pipeline | Threads | LER: ms/Dokument (Median) | ms / 1000 Zeichen | Courts 8.000 Zeichen: ms/Dokument | ms / 1000 Zeichen |
|---|---|---|---|---|---|
| ohne GLiNER (Baseline) | 1 | 14 (13) | 10 | 72 | 10 |
| + gliner_multi-v2.1 | 3 | 553 (423) | 428 | 4.015 | 536 |
| + gliner_multi-v2.1 | 1 | 1.241 (968) | 961 | 9.451 | 1.262 |
| + gliner-x-small | 3 | 317 (262) | 245 | 1.718 | 229 |

Die Batch-Läufe über ganze Splits (3 Threads, unter Last) lagen bei 0,6–1,0 s je 1000 Zeichen für multi-v2.1 und
0,3 s für x-small. Einordnung: Die bisherige Pipeline braucht rund 10 ms je 1000 Zeichen; GLiNER macht sie 25- bis
125-mal langsamer. Ein Schriftsatz von 20.000 Zeichen kostet mit multi-v2.1 rund 10 s (3 Kerne) bzw. 25 s (1 Kern)
zusätzlich vor dem LLM-Aufruf, mit x-small rund 5 s. Dazu kommen ca. 1,1 GB (multi-v2.1) bzw. 1,2 GB (x-small, fp32)
Modellgewichte, 2–3 GB RAM pro Prozess und PyTorch als Abhängigkeit. Ohne GPU ist das für interaktive Nutzung
(Chat, MCP) nicht vertretbar; mit GPU wäre die Latenz akzeptabel, ändert aber nichts an der fehlenden Präzision.

## Abnahme und Empfehlung

| Kriterium (AGENTS.md) | Ergebnis |
|---|---|
| Präzision sinkt nirgends | verletzt: jede Variante mit Recall-Gewinn senkt Präzision auf LER, Union auch auf Finance |
| Personen-Recall sinkt nicht | erfüllt (PER-Recall steigt bei Union leicht, aber PER-Präzision fällt) |
| Ziel ORG-Recall ≥ 0,65 bei P ≥ 0,90 | nicht erreicht |

Empfehlung:
1. **GLiNER bleibt standardmäßig aus.** Kein Eintrag in den Standard-Abhängigkeiten, keine Gewichte im Repo.
2. Für Rechtstexte nicht weiterverfolgen: Der Recall-Gewinn kommt fast nur über öffentliche Institutionen und
   Gattungswörter, die das Produkt bewusst nicht pseudonymisiert; dazu kommen 25- bis 125-fache Latenz vor dem
   LLM-Aufruf und mehrere GB zusätzliche Abhängigkeiten (PyTorch). Der verbleibende ORG-Fehlerrest in LER besteht
   ohnehin großteils aus Verbandskürzeln und Marken (siehe `org-ner-results.md`), die GLiNER ebenfalls kaum trifft.
3. Mögliche spätere Nutzung, jeweils erst nach eigener Messung: (i) Support-/Finanztexte, wo die Union deutlichen
   Recall bringt, sofern eine Präzisionsmessung an echten (lokal annotierten) Beispielen das trägt;
   (ii) GLiNER als Lehrer für Silberlabels auf unannotierten Gerichtstexten (offline, Latenz egal), gefiltert durch
   die Regeln und eine Behörden-Stoppliste, um `de_legal_ner` nachzutrainieren.
4. Für den Firmen-Recall sind die nächsten Hebel weiterhin Feedback-Daten (`--feedback`) und GermEval-2014-ORG
   als Zusatztraining, sowie die Produktentscheidung, ob Verbände/Gewerkschaften/Marken überhaupt pseudonymisiert
   werden sollen.

## Reproduzieren

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu   # optional, sonst CUDA-Build
pip install -e "packages/core[gliner]"            # gliner-x-* zusätzlich: pip install stanza langdetect
export ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_legal_ner/ner"
ANONYMIZER_GLINER_MODEL=urchade/gliner_multi-v2.1 ANONYMIZER_GLINER_TYPES=organization ANONYMIZER_GLINER_THRESHOLD=0.95 \
  python packages/core/scripts/ler_data.py eval --split test --data <Kopie von datasets/ler>
ANONYMIZER_GLINER_MODEL=urchade/gliner_multi-v2.1 ANONYMIZER_GLINER_TYPES=person,organization,location \
  python packages/core/scripts/court_data.py eval --split test --data <Kopie von datasets/courts>
env -u ANONYMIZER_NER_MODEL_DE ANONYMIZER_GLINER_MODEL=urchade/gliner_multi-v2.1 \
  ANONYMIZER_GLINER_TYPES=person,organization,location python packages/core/scripts/finance_data.py eval --data <Kopie>
```

Ein voller Lauf über einen Split dauert mit GLiNER-Base auf 3 CPU-Kernen 15–30 Minuten (statt unter einer Minute).
