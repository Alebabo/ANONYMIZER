# Personen-Recall im deutschen juristischen NER: Fehleranalyse und Ergebnisse vom 21.11.2026

Ziel: höherer Recall für Personen in der Pipeline Regeln + `de_core_news_lg` + `models/de_legal_ner/ner`, ohne
Präzision (gesamt) oder Personen-Recall auf LER, Courts oder den Finanzdaten zu verlieren. Kein Neutraining:
nur Regeln und Logik in `packages/core/src/anonymizer/detect/`.

## Ergebnis

| Messung (Test-Splits, komplette Pipeline) | Vorher | Nachher |
|---|---|---|
| LER test: gesamt P / R / F1 (partial overlap) | 0.923 / 0.751 / 0.828 | 0.923 / **0.782** / 0.847 |
| LER test: Personen P / R | 0.912 / 0.836 | 0.914 / **0.914** |
| LER test: Organisationen / Orte P / R | 0.883 / 0.538, 0.967 / 0.864 | unverändert |
| LER test: Personen TP / FP / FN | 271 / 26 / 53 | 296 / 28 / 28 |
| LER test: PER/ORG/LOC-Treffer auf Gerichten, Normen, Rechtsprechung | 16 | 18 |
| LER dev: gesamt P / R | 0.904 / 0.766 | 0.908 / 0.801 |
| LER dev: Personen P / R | 0.894 / 0.851 | 0.903 / 0.931 |
| Courts test: eingesetzte Werte gefunden (859) | 0.995 | 0.995 |
| Courts test: Personen | 814 / 818 | 814 / 818 |
| Finanzdaten (gretel / syntriq / EasyOctopus): geschützt | 0.655 / 0.905 / 0.586 | unverändert |
| Finanzdaten: Präzision (untere Schranke) | 0.372 / 0.550 / 0.702 | unverändert |

Die Finanzdaten werden wie bisher ohne Rechtsmodell gemessen; dort ändert sich keine einzige Detektion (siehe
unten, warum die neue Prüfung nur mit `de_legal_ner` läuft). Alle Entscheidungen wurden auf LER dev getroffen,
Test erst danach gemessen. Die beiden zusätzlichen Treffer auf Rechtsprechung im Test sind „Fini“ in
„EuGH-Urteil Fini H“ (Name einer Partei im Entscheidungsnamen).

## Fehleranalyse (LER dev, 52 verpasste Personen vor der Änderung)

| Kategorie | Anzahl | Beispiel | Jetzt gefunden |
|---|---|---|---|
| Richtername allein als Satz (Unterschriftenzeile) | 32 | „… entschieden. **Fieback** bb) Aus den …“, „**Raum** Nicht anders als …“ | 25 |
| Weitere Richter einer Besetzung, Abkürzung „RiBGH“ | 3 | „der Richter Jacobi und **Schödel**“, „RiBGH **Gericke**“ | 3 |
| Nachname oder voller Name im Fließtext ohne Anrede/Rolle | 9 | „Torhüter **Hodžić**“, „Betriebs der **Nikolaidis**“ | 0 |
| Als Organisation typisiert | 3 | „Ablehnungsschreiben des **Albrecht**“ | 0 |
| Platzhalter, Decknamen, Literatur | 4 | „Zeugen **W ...**“, „**XX**“, „**Oberdisse, E.**“ | 0 |
| Spangrenze (Teil gefunden, Rest nicht) | 1 | „**Natalia Do**“ | 0 |

Die übrigen Kategorien aus der Aufgabenstellung (Titel/Anrede, Adelsprädikate, Bindestrichnamen, Großschreibung,
Genitiv-s, „Kläger Müller“) kamen unter den verpassten Personen nicht oder nur einzeln vor; Anrede und
Prozessrolle deckt `PersonRecognizer` bereits ab, Großschreibung und Nachnamen die Propagation.

Ursache der größten Kategorie: In LER steht die Unterschrift eines Richters als eigener Satz, in echten
Entscheidungen als eigene Zeile. Im zusammengesetzten Text liest das Modell sie als Anfang des nächsten Satzes.
Oft erkennt NER den Namen sogar, aber der Wortart-Filter (`_name_like`) verwirft ihn: Der Tagger hält unbekannte
Nachnamen wie „Fieback“, „Hayen“, „Raum“ oder „Grube“ für Substantive.

## Umgesetzt

1. **Einzelwort-Prüfung für Unterschriftenzeilen** (`ner.py`, `_ISOLATED`, `SpacyRecognizer._isolated_names`):
   ein großgeschriebenes Wort, das allein als Satz oder Zeile steht (davor Satzende oder Zeilenanfang, danach
   Zeilenende, Aufzählung wie „bb)“, „(1)“, „III.“ oder ein großgeschriebenes Wort), wird noch einmal allein durch
   NER geschickt. Nur wenn das Modell es dann als Person markiert, wird es übernommen; der Wortart-Filter entfällt
   dafür. Überschriften („Tatbestand“, „Geltungsbereich“, „Urlaub“, „Präambel“) sind für das Modell allein keine
   Personen. Ausgeschlossen: Abkürzungen und Aufzählungen davor („u. a.“, „2.“), Anführungszeichen, Doppelpunkte,
   Adjektivendungen („Statthafte“, „Gleichheitsrechtliche“) und Beglaubigungsvermerke („Beglaubigt“,
   „Urkundsbeamter“). Auf LER dev: +25 Personen, 0 neue Fehltreffer.
   Nur mit `de_legal_ner`: Das Standardmodell und `de_c24_ner` nennen fast jedes Einzelwort eine Person
   („Kreditkartenauszug“, „Loan“, „Passiva“); auf den Finanzdaten waren das über 240 Fehltreffer.
2. **Besetzung des Gerichts** (`recognizers.py`, `PersonRecognizer._bench`): nach „der/die Richter X“ werden
   weitere Namen der Aufzählung („, Dr. Y und Z“) übernommen. Nur nach einem Artikel (sonst „für Richter,
   Staatsanwälte und Rechtspfleger“), Abbruch bei Funktionswörtern, Titeln („Dipl. - Phys.“) und Wörtern auf
   „-richter“. Dazu „Richterinnen“ und Abkürzungen wie „RiBGH“, „VRiBGH“ als Richterrolle.

Tests: `packages/core/tests/test_person_recall.py` (Kandidatenmuster, Ausschlüsse, Besetzung, Einschränkung auf das
Rechtsmodell, Ende-zu-Ende mit `de_legal_ner`, falls die Gewichte vorhanden sind).

## Verworfen oder nicht umgesetzt

- **Einzelwort-Prüfung mit dem Standardmodell**: auf den Finanzdaten über 240 neue Fehltreffer (s. o.), daher auf
  `de_legal_ner` beschränkt.
- **Erste Fassung des Musters** (Anführungszeichen und Doppelpunkt als Satzgrenze, ohne Adjektivfilter): auf LER dev
  14 neue Fehltreffer („" Schmucke Sache "“, „" Eli Lilly "“, „Statthafte“). Präzision sank, daher eingeschränkt.
- **Nachnamen im Fließtext ohne Hinweiswort** (9 Fälle): ohne Anrede, Rolle oder zweites Vorkommen gibt es kein
  regelbasiertes Signal, das nicht zugleich Firmen- und Ortsnamen trifft. Das ist Aufgabe des Modells
  (Neutraining, nicht Teil dieser Arbeit).
- **Spangrenzen bei Aktenzeichen und Adressen** (Zusatzaufgabe: „Az.: 12 C 345/24\nDer“, „10115 Berlin\n\nIn“):
  Ursache gefunden (`\s` statt `[ \t]` und keine Satzgrenze in `CASE_NUMBER` und `_DE_CITY`) und behoben, aber nicht
  in diesen Branch übernommen: auf den Finanzdaten sinkt die Präzisions-Untergrenze leicht (syntriq 0.5499 ->
  0.5495, gretel 0.3718 -> 0.3717), weil der nun freie Text der Folgezeile („Amtsgericht Leipzig“,
  „Neubrandenburg“, „Personalnr“) eigene Treffer bekommt. Der Fix liegt separat im Branch
  `claude/peaceful-keller-md3af4-span-fix` zur Entscheidung.

## Reproduktion

```bash
export ANONYMIZER_NER_MODEL_DE="de_core_news_lg+models/de_legal_ner/ner"
python packages/core/scripts/ler_data.py eval --split test     # bzw. --split dev
python packages/core/scripts/court_data.py eval --split test
unset ANONYMIZER_NER_MODEL_DE
python packages/core/scripts/finance_data.py eval             # gretel vorher: finance_data.py download
```
