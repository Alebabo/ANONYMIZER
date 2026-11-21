# ORG-Recall im NER: Recherche (21.11.2026)

Kennzeichnung: **[Q]** = durch Quelle belegt, **[o.Q.]** = Wissen ohne Quelle (Suche ergab nichts), bitte vor Verwendung prüfen.

## Kurzfazit

- Größter Hebel: **GLiNER (Apache-2.0) als zweiter Detektor** plus **Kontext-Cues/EntityRuler**, danach Daten (GermEval 2014) nachtrainieren.
- CoNLL-2003 deutsch ist für ein Apache-2.0-Repo/kommerziellen Kunden **nicht nutzbar** (akademische Nutzung). GermEval 2014 ist CC BY und nutzbar.
- Ein de_core_news_trf mit NER konnte ich **nicht belegen**; `de_dep_news_trf` hat laut Dateilisting keine NER-Komponente.

## 1. Datensätze mit ORG-Labels

| Datensatz | Lizenz | Größe | Bemerkung |
|---|---|---|---|
| GermEval 2014 (NoSta-D) | CC BY (offiziell); HF-Card widersprüchlich (cc-by-4.0 vs. Link auf BY-SA) [Q] | 24.000 / 2.200 / 5.100 Sätze, >590k Tokens [Q] | ORG plus Unterklassen `ORGderiv`/`ORGpart` [Q]. Quelle: Wikipedia + Nachrichten. ORG-Anzahl nicht gefunden. |
| CoNLL-2003 deutsch | Frankfurter Rundschau, nur Annotationen verteilt, Nutzung nur akademisch [Q, sekundär] | o.Q. | Für uns ausschließen. |
| WikiANN / PAN-X | Lizenz für de nicht verifizierbar (HF: "unknown") [Q]; Wikipedia-Ableitung, ODbL/BY-SA plausibel [o.Q.] | o.Q. | Maschinell erzeugte Silberlabels, rauschig; ORG-Definition Wikipedia-Titel. Nur als Zusatz, erst Lizenz klären. |
| Europarl-NER (Agerri) | Lizenz nicht gefunden; Europarl-Nutzungsbedingungen könnten vererbt sein [Q, unklar] | o.Q. | Parlamentsdomäne, wenig Firmen. Niedrige Priorität. |
| NoSta-D | CC BY [Q] | = Basis von GermEval 2014 | Nicht separat nötig. |

Quellen: https://www.inf.uni-hamburg.de/en/inst/ab/lt/resources/data/germaner.html, https://huggingface.co/datasets/germeval_14/blob/main/README.md, https://aclanthology.org/L14-1251/, https://huggingface.co/datasets/unimelb-nlp/wikiann, https://www.clips.uantwerpen.be/conll2003/ner, https://www.inf.uni-hamburg.de/en/inst/ab/lt/publications/2014-benikovaetal-lrec-german-ner.pdf

Kritik: GermEval-ORG ist Presse/Wikipedia-Stil. Rechtstexte anonymisieren Firmen oft als "die Beklagte", Kürzel und Familienunternehmen. Der Gewinn ist begrenzt, aber billig. Unser eigener Trainingscode hat bereits einen `--germeval`-Schalter (README, aktuell 0).

## 2. Vortrainierte Modelle

| Modell | ORG/Gesamt-F1 | Größe/CPU | Lizenz |
|---|---|---|---|
| `flair/ner-german-large` | Gesamt-F1 92,31 (CoNLL-03 de revised) [Q]; ORG nicht ausgewiesen | XLM-R large, ca. 560M Parameter [Q, sekundär] → auf CPU langsam (o.Q.) | auf Card nicht gefunden; CoNLL-Trainingsdaten problematisch, Weitergabe vermutlich eingeschränkt [o.Q.] |
| `stefan-it/span-marker-gelectra-large-germeval14` | Gesamt-F1 89,08 GermEval14 [Q]; ORG nicht ausgewiesen | gelectra-large, o.Q. | MIT (Modell) [Q]; Trainingsdaten CC BY |
| `gwlms/span-marker-bert-germeval14` | 87,45 [Q] | BERT-Base-Klasse | CC BY 4.0 [Q] |
| `urchade/gliner_multi-v2.1` | Kein deutscher ORG-Wert gefunden [Q: Recherche ergebnislos] | o.Q. (Base-Größe, ca. 0,2-0,5 GB) | Apache-2.0 [Q]; altes `gliner_multi` v0 war CC BY-NC, nicht verwenden [Q] |
| spaCy `de_core_news_lg` | Selbstberichtet NER-F1 ca. 85 [Q] | 568 MB | MIT [Q] |
| spaCy `de_core_news_trf` | Existenz/NER nicht belegbar; `de_dep_news_trf` ohne NER [Q] | 410 MB | MIT [Q] |

Quellen: https://huggingface.co/flair/ner-german-large, https://huggingface.co/stefan-it/span-marker-gelectra-large-germeval14, https://huggingface.co/gwlms/span-marker-bert-germeval14, https://huggingface.co/urchade/gliner_large-v2.1, https://arxiv.org/pdf/2311.08526, https://huggingface.co/spacy/de_core_news_lg, https://huggingface.co/spacy/de_dep_news_trf/tree/main

Kritik: Alle Gesamt-F1-Werte sind auf Zeitungs-/Wikipedia-Daten gemessen und sagen wenig über Rechtstexte. CPU-Latenz habe ich nicht belegt; selbst messen. Ein Transformer-Modell sprengt ggf. das CPU-Budget beim Kunden.

## 3. Techniken für mehr ORG-Recall

- **Kontext-Cues / EntityRuler (Regeln, o.Q. zur Wirksamkeit):** Muster wie "die Firma X", "Arbeitgeberin X", "Beklagte zu 2 (X)", "X-Gruppe", "X GmbH & Co." in Großschreibung. Hoher Recall-Gewinn bei Rechtstexten, kontrollierbare Präzision, kein Training. Gegenmaßnahme: Gerichte/Behörden-Stoppliste (bei uns bewusst nicht ORG).
- **Gazetteer aus GLEIF:** LEI-Daten sind CC0, Golden Copy täglich verfügbar [Q: https://www.gleif.org/en/about/open-data, https://www.gleif.org/en/lei-data/gleif-golden-copy/download-the-golden-copy]. Enthält aber nur LEI-pflichtige (meist große/finanznahe) Rechtsträger, kaum Mittelstand. Handelsregister: Lizenz nicht gefunden (Suche ergebnislos), OpenCorporates nicht recherchiert (o.Q., laut meiner Kenntnis ODbL/Share-Alike-Problem). Gazetteer nur mit Rechtsform-Normalisierung und Mindestlänge, sonst Präzisionsverlust ("Haas" = Nachname).
- **Ensemble spaCy + GLiNER (o.Q. zur Wirkung):** Vereinigung für Label ORG mit Schwelle; GLiNER erkennt Zero-Shot-Labels wie "Unternehmen", "Marke", "Verband". Präzision per Schwelle und Regelfilter steuern, auf LER-Test messen.
- **Synthetische Firmennamen (analog zu euren synthetischen Personennamen):** Firmenlisten in reale Gerichtstexte einsetzen (inkl. Kurzformen, Abkürzungen, Marken). Trainingsstück, das "ohne Rechtsform" direkt adressiert. Risiko: Muster-Überanpassung, deshalb Mischung aus Namen mit/ohne Rechtsform.
- **Distillation (o.Q.):** GLiNER/Transformer als Lehrer auf unlabeled Gerichtstexten, Silberlabels für spaCy. Aufwändiger, Lizenz der Lehrer beachten (Apache/MIT ok).

## 4. Rangliste der nächsten Schritte

1. **GLiNER-Ensemble für ORG messen (1-2 Tage, Gewinn ORG-Recall ca. +10-20 Punkte, Schätzung ohne Quelle).** `gliner_multi-v2.1` offline, Labels "Unternehmen/Organisation/Marke/Verband", Vereinigung mit spaCy, Schwelle auf LER-dev tunen, Gerichte/Behörden filtern. Zuerst CPU-Latenz und RAM messen; ist beides zu hoch, nur für Schritt 3 als Lehrer nutzen.
2. **Kontext-Cue-Regeln plus Stoppliste (2-3 Tage, Gewinn mittel, Präzision stabil).** Rein regelbasiert, deterministisch, kein Modellwechsel. Auf LER und Gerichtsdaten messen.
3. **Synthetische Firmennamen und GermEval-2014-ORG in Training (3-5 Tage, Gewinn unsicher, ca. +5-10 Punkte).** GLEIF als Namenspool (CC0), Firmen in bestehende Court-Blöcke einsetzen. GermEval nur ORG-Basisklassen verwenden, Derivate (`ORGderiv/part`) verwerfen. Zuvor Ablation: nur Synthetik vs. mit GermEval.

Nicht empfohlen: CoNLL-2003 deutsch (Lizenz), flair-large (Größe/Lizenz ungeklärt), WikiANN (Lizenz und Labelqualität offen).

## Offene Punkte

- ORG-F1 pro Klasse für GLiNER/Gelectra auf Deutsch: nicht gefunden, selbst messen.
- Lizenz WikiANN-de, Europarl-NER, Handelsregister, OpenCorporates, flair-Modelle: ungeklärt.
- Existenz eines spaCy-Modells `de_core_news_trf` mit NER: nicht bestätigt.
