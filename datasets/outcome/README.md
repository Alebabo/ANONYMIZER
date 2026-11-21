# Machbarkeitsexperiment: Ausgang von Kündigungsschutzklagen vorhersagen

Frage: Lässt sich aus dem Sachverhalt (Tatbestand) einer Kündigungsschutzklage vorhersagen, ob die Klage
erstinstanzlich Erfolg hat? Ziel ist eine belastbare Zahl, kein Produktfeature.

## Ergebnis in Kürze

- **Datensatz:** 3.226 Urteile aus 71 Gerichten aus den Jahren 1985–2026. Davon stammen 2.455 von Landesarbeitsgerichten (LAG); bei ihnen zählt der Sachverhalt der ersten Instanz. Die übrigen 771 stammen von Arbeitsgerichten (ArbG).
- **Labels:** abgewiesen 1.474 (46 %), stattgegeben 1.333 (41 %), teilweise 419 (13 %).
- **Label-Genauigkeit (Handprüfung):** 90 % (27 von 30) in Runde 2. Runde 1 ergab 86,7 % und führte zu Regelkorrekturen.
- **Bestes Modell:** TF-IDF mit logistischer Regression.
  - Macro-F1 beim zeitlichen Split (realistisch): **0,44** (95-%-KI 0,40–0,47), Accuracy 49 %.
  - Beim zufälligen Split: 0,51 (0,46–0,55), Accuracy 58 %.
  - Die stärkste Baseline nur aus Metadaten (Gericht oder Jahr) liegt bei 0,29 bzw. 0,36.
- **Binär** (Bestandsschutz erfolgreich ja/nein): Macro-F1 0,62 beim zeitlichen Split, 0,66 beim zufälligen.
- **Leakage-Probe:** Ein Klassifikator, der nur offensichtliche Ausgangsphrasen kennt, erreicht auf der Eingabe 0,33–0,37 Macro-F1 und liegt damit auf Baseline-Niveau. Auf dem Tenor erreicht dieselbe Probe zur Kontrolle 0,81–0,86. Die Eingabe verrät den Ausgang also nicht offensichtlich.
- **Fazit: Als Produktfeature lohnt es sich in dieser Form nicht.** Es gibt ein messbares, aber schwaches Signal. Begründung unten.

## Daten

**Quelle:** [`openlegaldata/court-decisions-germany`](https://huggingface.co/datasets/openlegaldata/court-decisions-germany), Dump `dump-20260520` (54 Parquet-Dateien, 10,7 GB), Open Legal Data, Lizenz ODbL 1.0.

**Zugang:** Das Dataset ist *gated*. Man braucht einen Hugging-Face-Account, der die Bedingungen akzeptiert hat, und dessen Token (`HF_TOKEN`). Die öffentliche API de.openlegaldata.io kommt als Alternative nicht in Frage: Anonym sperrt sie nach etwa 45 Anfragen für rund einen Tag.

**Filter (`build`):**

| Schritt | Urteile |
|---|---:|
| Urteile der Arbeitsgerichtsbarkeit im Dump (`type == "Urteil"`) | 26.765 |
| davon BAG (weggelassen) | −5.062 |
| kein Kündigungsschutzantrag im Text | −15.675 |
| LAG ohne Wiedergabe des ArbG-Urteils im Tatbestand | −726 |
| Tenor oder Tatbestand nicht gefunden | −159 |
| Label unklar → verworfen | −1.496 |
| Eingabe < 400 Zeichen | −179 |
| Dubletten (Gericht + Aktenzeichen oder gleicher Textanfang) | −242 |
| **Datensatz** | **3.226** |

Ein Urteil gilt als Kündigungsschutzfall, wenn der Text einen Antrag der Form *"festzustellen, dass das
Arbeitsverhältnis … durch die Kündigung … nicht aufgelöst/beendet"* enthält, das Wort Kündigungsschutzklage oder
Kündigungsschutzantrag vorkommt oder ein Satz *"Die Parteien streiten über die (Rechts-)Wirksamkeit … Kündigung"*
auftaucht.

### Entscheidung zu LAG

LAG-Urteile machen 76 % der Fälle aus. Ohne sie gäbe es nur 771 Fälle. Ihr Tatbestand gibt das Urteil des
Arbeitsgerichts wieder ("Das Arbeitsgericht hat die Klage abgewiesen …"). Deshalb gilt für LAG-Fälle:

- **Eingabe:** nur der Teil des Tatbestands **vor** diesem Satz, also Sachverhalt, Parteivortrag und Anträge der ersten Instanz.
- **Label:** der **erstinstanzliche** Ausgang aus diesem Satz.

So haben ArbG- und LAG-Fälle dasselbe Ziel, nämlich den Ausgang vor dem Arbeitsgericht. Der Preis ist eine Verzerrung:
Bei LAG-Fällen sind nur Verfahren dabei, gegen die Berufung eingelegt wurde.

### Labels

Die Regeln stehen in `label_tenor` (ArbG) und `label_first_instance` (LAG) in
`packages/core/scripts/outcome_experiment.py`. Vor dem Labeln werden Punkte in Daten, Beträgen und Abkürzungen
entfernt (`nodots`), damit Satzmuster nicht an "vom 17.10.2008" zerbrechen.

| Label | Bedeutung |
|---|---|
| stattgegeben | Arbeitsverhältnis durch die Kündigung(en) nicht aufgelöst bzw. Kündigung unwirksam, keine Teilabweisung |
| teilweise | Bestandsschutz erfolgreich, aber "im Übrigen abgewiesen" (meist Nebenanträge wie Zahlung, Zeugnis oder Weiterbeschäftigung), **oder** Beendigung erst zu einem späteren Termin, Auflösung gegen Abfindung, "überwiegend/im Wesentlichen stattgegeben" |
| abgewiesen | Klage (insgesamt) abgewiesen ohne Erfolgsausspruch |
| verworfen | Teil- oder Versäumnisurteil, unzulässig, Erledigung durch Vergleich, anderes Verfahren ("mittlerweile rechtskräftig …"), Abfindungs- oder Zahlungsklage ohne Bestandsschutz, sonst unklar |

"teilweise" vermischt zwei Bedeutungen: echten Teilerfolg im Bestandsschutz und abgewiesene Nebenanträge. Deshalb
gibt es zusätzlich die binäre Auswertung *Bestandsschutz erfolgreich* (stattgegeben + teilweise) gegen *abgewiesen*.

**Handprüfung** (`label_check_runde1.json`, `label_check_runde2.json`; je 30 Zufallsfälle, Tenor bzw. ArbG-Satz gelesen):

| Runde | korrekt | Fehlerarten |
|---|---:|---|
| 1 | 26/30 (86,7 %) | 2× Satz aus anderem Verfahren, 1× "überwiegend stattgegeben" als stattgegeben, 1× Abfindungsklage |
| 2 (nach Korrektur, neue Stichprobe) | 27/30 (90 %) | 1× Schadensersatzklage (Falltyp), 1× Vergleichserledigung als abgewiesen, 1× "im Wesentlichen stattgegeben" |

Die beiden Regelfehler aus Runde 2 sind danach behoben. Falltyp-Fehler bleiben: Fälle, die gar keine
Kündigungsschutzklage sind, aber ein Kündigungsthema haben. Realistisch sind etwa 90–95 % der Labels korrekt.
Damit liegt auch die erreichbare Obergrenze unter 1,0.

### Eingabe und Leakage-Kontrolle

- **Eingabe:** nur der Tatbestand, bei LAG nur der erstinstanzliche Teil.
- **Entfernt:** Tenor, Entscheidungsgründe, Leitsatz und Rechtsmittelbelehrung (der Text wird nicht verwendet), außerdem:
  - Sätze mit Verfahrens- oder Ausgangsbezug: *stattgegeben, abgewiesen, Urteil, Versäumnisurteil, Kammer, Gericht, Arbeitsgericht, Berufung, Revision, Beweisaufnahme, Protokoll, Gütetermin, Vergleich* usw.,
  - Daten (→ `DATUM`) und Aktenzeichen (→ `AZ`).
- **Gerichts- und Richternamen:** Sie stehen in Sätzen mit "Gericht"/"Kammer" und fallen damit weg. Richternamen stehen ohnehin nur unter den Gründen.
- **Leakage-Probe:** eine logistische Regression nur auf 22 offensichtlichen Ausgangsphrasen (*unwirksam, sozial gerechtfertigt, nicht aufgelöst, Abfindung, Berufung, Urteil* …):

| Split | Probe auf Eingabe | Probe auf Tenor (Kontrolle) | bestes Modell |
|---|---:|---:|---:|
| zufällig | 0,34 | 0,86 | 0,51 |
| zeitlich | 0,37 | 0,83 | 0,44 |
| Gericht | 0,33 | 0,85 | 0,47 |

Die Probe liegt auf der Eingabe auf dem Niveau der Metadaten-Baselines und weit unter der Kontrolle.

## Ergebnisse

Modelle laufen auf der CPU, mit `class_weight="balanced"`:
- `tfidf_logreg`: TF-IDF über Wörter (1–2-Gramme) und Zeichen (3–5-Gramme), dazu logistische Regression.
- `tfidf_linsvm`: dieselben Merkmale mit linearer SVM.

Baselines:
- *Mehrheit*: immer die häufigste Klasse im Training.
- *nur Gericht*: die häufigste Klasse je Gericht.
- *nur Jahr*: die häufigste Klasse je Jahr.

Die 95-%-Konfidenzintervalle stammen aus einem Bootstrap über die Testfälle.

### Macro-F1 (3 Klassen)

| Split | n Train / Test | Mehrheit | nur Gericht | nur Jahr | LogReg | LinSVM | LogReg binär |
|---|---|---:|---:|---:|---:|---:|---:|
| zufällig (stratifiziert 80/20) | 2.580 / 646 | 0,21 | 0,36 | 0,35 | **0,51** [0,46–0,55] | 0,49 | 0,66 |
| zeitlich (Test ab 04/2019) | 2.580 / 646 | 0,20 | 0,29 | 0,20 | **0,44** [0,40–0,47] | 0,42 | 0,62 |
| nach Gericht (ungesehene Gerichte) | 2.548 / 678 | 0,21 | 0,21 | 0,32 | **0,47** [0,43–0,51] | 0,46 | 0,65 |
| zeitlich + Gericht | 2.095 / 193 | 0,20 | 0,20 | 0,20 | **0,42** [0,35–0,49] | 0,43 | 0,63 |

### Accuracy, Recall je Klasse und Brier-Score (LogReg)

| Split | Accuracy | Recall abgewiesen | Recall teilweise | Recall stattgegeben | Brier | Brier Prior-Referenz |
|---|---:|---:|---:|---:|---:|---:|
| zufällig | 0,58 | 0,62 | 0,24 | 0,64 | 0,52 | 0,60 |
| zeitlich | 0,49 | 0,57 | 0,18 | 0,56 | 0,60 | 0,65 |
| Gericht | 0,55 | 0,59 | 0,17 | 0,66 | 0,58 | 0,62 |

Der Brier-Score ist multiklassig (0 = perfekt, 2 = maximal falsch). Die Prior-Referenz sagt immer die
Klassenverteilung des Trainings vorher. Das Modell ist nur wenig besser kalibriert als diese Referenz.

**Konfusionsmatrix, zeitlicher Split (LogReg)** – Zeilen: wahr, Spalten: vorhergesagt:

| | abgewiesen | teilweise | stattgegeben |
|---|---:|---:|---:|
| **abgewiesen** | 155 | 17 | 100 |
| **teilweise** | 46 | 24 | 61 |
| **stattgegeben** | 80 | 26 | 137 |

### Top-Features (LogReg, zufälliger Split)

- **abgewiesen:** *war seit, auf die, mit Ablauf, Kläger war, Ablauf, beklagte zu, Prüfung, AG, Zeugin, Mitarbeiter der, xxx* …
- **stattgegeben:** *Bereich, hat beantragt, bezog, Anlage, vgl Bl, beabsichtigten außerordentlichen, Arbeitsvertrag, Sozialauswahl, hält die, verheiratete Kläger* …
- **teilweise:** *hilfsweise fristgerecht, Auflösungsantrag, außerordentliche, fristlos hilfsweise, Auflösung, fristgerechten Kündigung, 10 Arbeitnehmer, durch andere* …

Es gibt keine Ausgangsphrasen unter den Top-Features, also keine offensichtliche Leakage. Ein Teil der Merkmale ist
aber **Stil** statt Inhalt: *xxx* ist ein Anonymisierungsstil einzelner Gerichte, *vgl Bl* und *hat beantragt*
sind Formulierungsgewohnheiten. Inhaltlich plausibel sind *Sozialauswahl* (häufiger Angriffspunkt bei
betriebsbedingter Kündigung), *hilfsweise fristgerecht* und *Auflösungsantrag* (typisch für Teilerfolge).

## Grenzen

- **Label-Rauschen:** etwa 90 % korrekt. Die teilweise-Klasse ist inhaltlich gemischt und kaum vorhersagbar (Recall um 0,2).
- **Selektionsbias:** Veröffentlicht werden nur ausgewählte Urteile. Bei 76 % der Fälle (LAG) wurde zudem Berufung eingelegt. Vergleiche, mit denen die meisten Kündigungsschutzverfahren in der Praxis enden, fehlen ganz. Der Datensatz bildet also nicht die Fälle ab, die eine Kanzlei auf den Tisch bekommt.
- **Eingabe ist kein echter Mandantensachverhalt:** Der Tatbestand ist vom Gericht nach dem Verfahren geschrieben. Auswahl und Gewichtung der Tatsachen spiegeln bereits die richterliche Sicht. Ein Sachverhalt aus dem Erstgespräch ist dünner und einseitig, die Leistung dort wäre eher schlechter.
- **Stil-Artefakte:** Einige Merkmale identifizieren Gerichte oder Schreibstile. Beim Gerichts-Split hält das Modell (0,47) aber recht gut, der Effekt ist also begrenzt.
- **Kleiner Test beim strengsten Split** (zeitlich + Gericht, n = 193): breite Konfidenzintervalle.
- **Nicht getestet:** Transformer-Embeddings bzw. LLM-basierte Klassifikation. Sie sind auf der CPU mit langen Tatbeständen (Median etwa 4.900 Zeichen) nicht in 30 Minuten machbar. Sie könnten einige Punkte bringen, an den Grenzen oben ändern sie nichts.

## Fazit: lohnt sich das?

**Nein, nicht als Produktfeature, und auch kein großer Folgeaufwand ohne neue Datenquelle.**

- Das Modell schlägt alle Baselines klar. Das Signal ist echt, aber schwach: Im realistischen zeitlichen Split
  liegt es bei rund 49 % Accuracy bei drei Klassen und Macro-F1 0,62 bei der binären Frage, ob die Kündigung
  unwirksam ist. Für eine Aussage gegenüber Mandanten ("Ihre Chancen stehen bei 70 %") ist das zu ungenau und kaum
  besser kalibriert als die Grundrate.
- Die Obergrenze ist strukturell gedeckelt: durch Label-Rauschen, Selektionsbias (Vergleiche fehlen, nur
  veröffentlichte und angefochtene Urteile) und den Abstand zwischen gerichtlichem Tatbestand und echtem
  Mandantensachverhalt. Ein stärkeres Modell (LLM) behebt keinen dieser Punkte.
- Aus Geschäftssicht: Ein Prognose-Feature mit dieser Güte erzeugt Haftungs- und Vertrauensrisiken, aber keinen
  belastbaren Mehrwert. Erfahrene Fachanwälte schätzen besser, die Grundrate ist frei verfügbar.
- Sinnvoller wäre: (a) **Argument- oder Risikofaktor-Extraktion** statt Ausgangsprognose (etwa Sozialauswahl
  gerügt, Betriebsratsanhörung, Abmahnung vorhanden), wo das Signal in den Top-Features sichtbar ist, oder (b) ein
  neuer Versuch nur mit **eigenen Kanzleidaten inklusive Vergleichen** als Zielgröße. Abbruchkriterium für jeden
  Folgeversuch: binär mindestens 0,75 Macro-F1 auf einem zeitlichen Split.

## Reproduzieren

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e "packages/core[dev]" scikit-learn pandas pyarrow huggingface_hub

# Optional (braucht HF-Token mit Dataset-Zugang, ~10,7 GB Download, Shards werden nach dem Filtern gelöscht):
HF_TOKEN=hf_... python packages/core/scripts/outcome_experiment.py download     # -> local/outcome/raw/
python packages/core/scripts/outcome_experiment.py build                         # -> local/outcome/cases.jsonl.gz

# Ohne Download: train/eval lesen datasets/outcome/raw/decisions.jsonl.gz, wenn local/outcome/cases.jsonl.gz fehlt
python packages/core/scripts/outcome_experiment.py train                         # ~6 min CPU
python packages/core/scripts/outcome_experiment.py eval                          # -> datasets/outcome/results.json, labels.csv
```

`build` braucht das HTML aus dem Download. `train` und `eval` laufen auch nur mit dem committeten Paket und ergeben
dieselben Fälle und Splits (geprüft).

## Dateien

| Datei | Inhalt |
|---|---|
| `raw/decisions.jsonl.gz` (7 MB) | 3.226 Fälle, sortiert nach id: `id, court, level, date, file_number, type, label, label_quelle, tenor` (ArbG-Tenor bzw. Wiedergabe des ArbG-Urteils, gekürzt), `x` (bereinigter Eingabetext), `splits` |
| `labels.csv` | id, Gericht, Instanz, Datum, Aktenzeichen, Label, Label-Quelle, Split-Zuordnung je Split-Art |
| `results.json` | alle Metriken, Konfusionsmatrizen, Top-Features, Build-Statistik, Handprüfungen |
| `label_check_runde1.json`, `label_check_runde2.json` | Handprüfungen der Labels |

Lizenz: ODbL 1.0 (abgeleitet von Open Legal Data), siehe `THIRD_PARTY_NOTICES.md`.
