# Messung an echten Kanzleitexten (lokal, ohne Cloud)

Diese Anleitung richtet sich an eine berechtigte Person in der Kanzlei, die keine Entwicklerin sein muss. Sie
misst, wie zuverlässig OpenAnonymizer Namen und andere personenbezogene Daten in **Ihren eigenen** Schriftsätzen
und Mandantenmails findet. Zeitbedarf: etwa 30 Minuten für fünf bis zehn Dokumente.

Alles läuft auf Ihrem Rechner. Das Mess-Kit nutzt kein Netzwerk. Die Texte, Ihre Markierungen und die Liste der
übersehenen Werte bleiben im Ordner `local/messung/` und werden von Git nie erfasst. Weitergegeben wird am Ende
nur ein Bericht mit Zahlen.

## Was Sie brauchen

- Einen Rechner, auf dem OpenAnonymizer bereits eingerichtet ist und der Selbsttest durchläuft (einmalig durch
  die IT, siehe nächster Abschnitt). Danach ist keine Internetverbindung nötig.
- Fünf bis zehn typische Dokumente: Schriftsätze, Mandantenmails, Vermerke. Formate: `.txt`, `.docx`, `.pdf`
  (nur mit Textebene; eingescannte PDFs ohne Text werden gemeldet und können nicht gemessen werden). Mails am
  einfachsten als Text kopieren und als `.txt` speichern.
- Einen einfachen Texteditor: Editor (Windows), TextEdit im Modus „Reines Textformat“ (macOS) oder einen
  Code-Editor. Kein Word, kein Online-Editor, kein KI-Assistent.

Bitte vorher prüfen: Der Projektordner darf nicht in einem Cloud-Speicher liegen, der automatisch synchronisiert
(OneDrive, Dropbox, iCloud). Sonst würden die Texte doch das Gerät verlassen.

## Vorab: Einrichtung durch die IT (einmalig, ca. 20 Minuten)

Benötigt werden Python ab 3.11, Git und Git LFS, etwa 2 GB Speicher und für die Einrichtung einmalig Internet. Im
Projektordner:

```
git lfs pull
python -m venv .venv
```

Aktivieren: unter Windows `.venv\Scripts\activate`, unter macOS/Linux `source .venv/bin/activate`. Dann:

```
pip install -e packages/core
git lfs pull   # German NER model Cato (packages/core/models/cato-1.1)
python -m spacy download en_core_web_lg
python packages/core/scripts/local_eval.py selbsttest
```

Hinter einem Firmen-Proxy brauchen `pip` und der Modell-Download `HTTPS_PROXY` und ggf. das Firmen-CA-Zertifikat
(`PIP_CERT`, `REQUESTS_CA_BUNDLE`). Wer den Download nicht freigeben kann: die Modellpakete
`en_core_web_lg-3.8.0` (Cato kommt mit dem Repo) von github.com/explosion/spacy-models/releases auf einem anderen
Rechner laden und mit `pip install <datei>.whl` installieren.

Der Selbsttest misst vier mitgelieferte, ausgedachte Dokumente (`examples/local-eval/`, schon korrigiert) und
schreibt nichts. Erwartete Ausgabe: `Einrichtung in Ordnung`. Meldet er `PROBLEM`, fehlt das Sprachmodell oder
Cato (`git lfs pull`); dann nicht mit echten Texten beginnen. Die Beispiele zeigen auch, wie korrigierte
Dateien aussehen.

## Schritt 1: Ordner anlegen (1 Minute)

Ein Terminal im Projektordner öffnen (dem Ordner, in dem `STATUS.md` liegt) und eingeben:

```
python packages/core/scripts/local_eval.py setup
```

Unter Windows ggf. `py` statt `python`. Das Skript legt `local/messung/dokumente/` an und prüft dabei, dass Git
diesen Ordner ignoriert. Liegt ein Pfad im Repository, aber außerhalb von `local/`, bricht es ab.

## Schritt 2: Dokumente hineinkopieren (5 Minuten)

Kopien der ausgewählten Dokumente nach `local/messung/dokumente/` legen. Wenn Sie Schriftsätze und Mails getrennt
auswerten wollen, Unterordner verwenden, zum Beispiel:

```
local/messung/dokumente/schriftsaetze/
local/messung/dokumente/mails/
```

Im Bericht erscheinen nur diese festen Gruppennamen: `schriftsaetze`, `mails`, `emails`, `vertraege`,
`gutachten`, `briefe`, `notizen`, `protokolle`, `urteile`, `beschluesse`, `vermerke`, `sonstige`. Jeder andere
Ordnername wird im Bericht durch `gruppe_1`, `gruppe_2` ersetzt. Dateinamen erscheinen nie im Bericht.

Auswahl: lieber unterschiedliche als viele ähnliche Dokumente. Bewusst auch schwierige Fälle aufnehmen:
ausländische Namen, Namen ohne Anrede, Firmen ohne Rechtsform, Mails mit Signatur.

## Schritt 3: Vorannotation erzeugen (2 Minuten)

```
python packages/core/scripts/local_eval.py annotate
```

Für jedes Dokument entsteht in `local/messung/annotiert/` eine Textdatei, z. B. `klage.docx.txt`. Darin ist
alles, was die Erkennung schützen würde, so markiert:

```
In Sachen [[Hans Beispielmann|PERSON]] ./. [[Kraftwerk Nord GmbH|FIRMA]]
```

Bereits vorhandene annotierte Dateien werden nicht überschrieben, Ihre Korrekturen gehen also nicht verloren.

## Schritt 4: Markierungen korrigieren (15 bis 20 Minuten)

Jede Datei im Texteditor öffnen und **den ganzen Text lesen**, nicht nur die Markierungen ansehen. Gesucht ist
vor allem, was die Erkennung übersehen hat.

| Fall | Was tun | Beispiel |
|---|---|---|
| Wert fehlt | mit `[[` und `\|TYP]]` einklammern | `[[Erika Musterfrau\|PERSON]]` |
| Markierung falsch | Klammern und `\|TYP` löschen, Wort stehen lassen | `[[Gruß\|PERSON]]` wird `Gruß` |
| Typ falsch | nur den Typ ändern | `[[Kraftwerk Nord GmbH\|ORT]]` wird `...\|FIRMA]]` |
| Markierung zu kurz oder zu lang | Klammern versetzen | `[[Hans\|PERSON]] Beispielmann` wird `[[Hans Beispielmann\|PERSON]]` |

Typen:

| Typ | Bedeutung |
|---|---|
| `PERSON` | Namen natürlicher Personen (Mandanten, Gegner, Zeugen, Anwälte, Richter) |
| `FIRMA` | Unternehmen, Vereine, private Organisationen |
| `ORT` | Orte, die einen Beteiligten erkennbar machen (Wohnort, Firmensitz) |
| `ADRESSE` | Postanschrift (Straße, Hausnummer, PLZ, Ort als ein Wert) |
| `EMAIL`, `TELEFON` | Kontaktdaten |
| `AKTENZEICHEN` | Aktenzeichen des eigenen Verfahrens oder der eigenen Akte |
| `GEBURTSDATUM` | Geburtsdatum |
| `BANK` | IBAN, BIC, Kartennummer |
| `NUMMER` | sonstige Kennnummern: Steuer-ID, Versicherungs-, Kunden-, Mandats-, Kfz-Kennzeichen |

**Nicht** markieren: Gerichte und Behörden, Gesetze und Paragrafen, zitierte veröffentlichte Entscheidungen samt
ihrem Aktenzeichen („BGH, Urteil vom 12.05.2021 – VI ZR 12/20“), Datumsangaben, Geldbeträge. Diese bleiben auch im
Betrieb lesbar.

Regeln:

- Jedes Vorkommen zählt einzeln. Steht ein Name dreimal im Text, wird er dreimal markiert.
- Den übrigen Text nicht verändern. Kleine Versehen schaden nicht, gemessen wird immer der Text, wie er in der
  Datei steht.
- Groß- und Kleinschreibung des Typs ist egal. Die Datei als UTF-8 speichern (Standard in den genannten Editoren).
- Anrede und Titel („Frau“, „Herrn“, „Dr.“, „Prof.“, „Rechtsanwältin“) gehören nicht zum Namen. Die Erkennung lässt
  sie lesbar. Wer sie mitmarkiert, macht nichts falsch: Sie werden beim Messen abgeschnitten.
- Eine Adresse wird als ein Wert markiert, auch über mehrere Zeilen. Die Anschrift eines Gerichts oder einer Behörde
  wird nicht markiert.
- Leere Zeilen zwischen Absätzen (bei `.docx` jeder zweite Zeilenumbruch) und `■` oder `�` statt Umlauten nicht
  „reparieren“. Steht beim `annotate` die Warnung „unlesbare Zeichen“, ist die PDF-Textebene fehlerhaft: Dann
  besser den Text als `.txt` speichern, das PDF entfernen und `annotate` erneut ausführen.

Eine Kurzfassung steht in `local/messung/annotiert/LIESMICH.txt`.

## Schritt 5: Prüfen (1 Minute)

```
python packages/core/scripts/local_eval.py check
```

- `FEHLER` mit Zeilennummer: eine Markierung ist unvollständig oder der Typ unbekannt. Korrigieren und erneut
  prüfen. Die Messung startet erst, wenn keine Fehler mehr gemeldet werden.
- `Hinweis`: ein markierter Wert kommt an einer anderen Stelle unmarkiert vor. Oft vergessen, manchmal richtig
  (z. B. ein Nachname als Teil eines Firmennamens). Nur prüfen.

## Schritt 6: Messen (2 Minuten)

```
python packages/core/scripts/local_eval.py eval
```

Die Erkennung läuft erneut über die Texte (ohne Ihre Markierungen) und wird mit Ihren Markierungen verglichen. Auf
dem Bildschirm erscheinen die Kennzahlen. In `local/messung/ergebnis/details.md` steht jede Abweichung mit
Textstelle:

- `VERPASST`: Wert wurde nicht erkannt und wäre an die KI gegangen. Das ist der wichtigste Fall.
- `TEILWEISE`: nur ein Teil wurde erkannt (z. B. Vorname ohne Nachname).
- `FALSCHER TYP`: verdeckt, aber mit anderem Typ (z. B. Firma als Ort). Für den Schutz unkritisch.
- `FALSCHER TREFFER`: etwas wurde verdeckt, das kein schützenswerter Wert ist. Kostet Lesbarkeit, nicht Schutz.

`details.md` enthält echte Namen. **Nicht weitergeben, nicht in Mails oder Chat-Programme kopieren.**

Die Kennzahlen:

| Kennzahl | Bedeutung |
|---|---|
| verdeckt R (Recall) | Anteil Ihrer markierten Werte, die die Erkennung überlappt; diese wären geschützt |
| vollständig verdeckt | Anteil, der ganz verdeckt ist (nicht nur der Vorname) |
| verdeckt P (Präzision) | Anteil der Treffer, die auf einem markierten Wert liegen |
| Typ P / R / F1 | wie oben, aber nur mit richtigem Typ |

Zum Vergleich: Auf veröffentlichten Urteilen liegt der Personen-Recall bei etwa 0,91 (siehe `STATUS.md`). Bei
kurzen, kleingeschriebenen Mails („hallo frau schmidt“) ist er deutlich niedriger; das ist bekannt und genau der
Grund für diese Messung.

Optional: Eigene Muster für Mandats- oder Kundennummern (siehe `HANDOVER.md`, Abschnitt 4.1) mitmessen:
`... eval --muster local/patterns.yaml` (ebenso bei `annotate`).

## Schritt 7: Bericht erzeugen und weitergeben (2 Minuten)

```
python packages/core/scripts/local_eval.py report
```

Das schreibt `local/messung/bericht.md`. Er enthält nur Zahlen: Anzahl Dokumente und Wörter, Präzision und
Recall je Typ und je Gruppe, Modell und Version. Keine Textausschnitte, keine Werte, keine Dateinamen. Vor dem
Schreiben prüft das Skript, dass keiner Ihrer markierten Werte im Bericht vorkommt; andernfalls bricht es ab.

Bitte den Bericht vor dem Versand einmal lesen und dann an das Entwicklerteam schicken.

## Schritt 8: Aufräumen

Wenn die Messung abgeschlossen ist, den Ordner `local/messung/` löschen (oder nur `bericht.md` behalten). Für eine
spätere Wiederholung mit einer neuen Version genügt es, `annotiert/` zu behalten und nur `eval` und `report`
erneut auszuführen; das Markieren entfällt dann.

## Häufige Meldungen

| Meldung | Bedeutung |
|---|---|
| `... liegt im Repository, aber nicht unter local/` | Ordner unter `local/` verwenden |
| `... wird von Git nicht ignoriert` | Eintrag `local/` in `.gitignore` fehlt; IT verständigen |
| `Hinweis: ... liegt in keinem Git-Repository` | erlaubt; selbst sicherstellen, dass der Ordner nicht geteilt wird |
| `WARNUNG: Die Namenserkennung (NER) lief nicht` | Sprachmodell fehlt; IT verständigen, Zahlen nicht verwenden |
| `Rechtsmodell nicht gefunden` | Modellgewichte fehlen (`git lfs pull`); es wird das Standardmodell gemessen |
| `PDF ... Seiten ohne Textebene` | eingescanntes PDF; Text nicht auswertbar, Dokument durch `.txt` ersetzen |
| `... unlesbare Zeichen (■, � ...)` | Textebene fehlerhaft (Schrift ohne Zeichentabelle); Text als `.txt` speichern |
| `PROBLEM: ...` beim Selbsttest | Einrichtung unvollständig; IT verständigen, nicht mit echten Texten messen |

## Für Entwickler

Skript: `packages/core/scripts/local_eval.py`, Tests: `packages/core/tests/test_local_eval.py`, Selbsttest-Daten
(synthetisch, Gold-Markierung): `examples/local-eval/`. Der Selbsttest schlägt fehl, wenn NER nicht läuft, das
Rechtsmodell fehlt oder der Personen-Recall unter 0,7 liegt (Stand 22.11.2026: Rechtsmodell 0,79, Standardmodell
0,83 Personen verdeckt; die Beispiele enthalten bewusst kleingeschriebene Mails). Bewertung mit
`anonymizer.ner_dataset.score_doc` (überlappende Treffer, wie `ler_data.py eval`) und dem Maß „verdeckt“ aus
`finance_data.py`. Nicht markiert und nicht bewertet werden die Typen, die die Policy `legal-default` lesbar
lässt (Gerichte, Gesetze, zitierte Aktenzeichen, Datum, Beträge) sowie Schlagwort-Treffer (Gesundheit, Marker).
Inline-Markierung wurde gewählt, weil sie ohne Zeichenpositionen auskommt und jeden Wert im Zusammenhang zeigt;
JSONL mit Offsets ist für Nicht-Entwickler im Editor nicht zuverlässig bearbeitbar.
