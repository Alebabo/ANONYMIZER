# Recherche: Ausgangsvorhersage Kündigungsschutzklagen

Stand: 2026-11-21. Webzugriff funktionierte nur über Suchsnippets; Volltexte (Papers, HF-Dataset-Card) wurden nicht geöffnet. Aussagen ohne URL sind als "ohne Quelle" markiert.

## Kurzfazit

- Für deutsche Arbeitsgerichte existiert nach dieser Suche kein veröffentlichter Benchmark; nächster Anker ist Swiss-Judgment-Prediction (SJP).
- Größtes Risiko: Der Tatbestand wird vom Gericht nach der Entscheidung geschrieben und leakt das Ergebnis. Ein hoher Score ist ohne Gegenmaßnahmen nicht glaubwürdig.
- Realistisch auf CPU: TF-IDF + lineares Modell. Erwartung Macro-F1 grob 0,55-0,70 (ohne Quelle, Schätzung).
- Regulatorisch ist ein Werkzeug für Anwälte deutlich unkritischer als eines für Verbraucher.

## 1. Veröffentlichte Arbeiten

- **Swiss-Judgment-Prediction** (Niklaus, Chalkidis, Stürmer, NLLP 2021)
  - Daten: ca. 85K Fälle des Schweizer Bundesgerichts, DE/FR/IT, 2000-2020, Label binär (Gutheißung/Abweisung). Eingabe: Sachverhalt (Facts), bis > 512 Token.
  - Modelle: Majority, TF-IDF + linear, BERT (512), erweiterte und hierarchische BERT-Varianten.
  - Bestwert: Hierarchical BERT ca. 68-70 % Macro-F1 (DE, FR).
  - Zeitlicher Split statt zufälliger 10-Fold-CV als Kernpunkt.
  - Quellen: https://arxiv.org/abs/2110.00806v1 , https://aclanthology.org/2021.nllp-1.3
  - Genaue Split-Jahre und Einzeltabelle: nicht verifiziert.
- **"One Law, Many Languages"** (Niklaus et al. 2023): aggregierter Macro-F1 über mehrere Schweizer Rechtsaufgaben nur 48,4, nicht direkt vergleichbar. https://arxiv.org/html/2306.09237v3
- **Bayerisches Korpus** (Urchs et al. 2021): über 32K Entscheidungen aus 131 Gerichten mit Metadaten inkl. Sachverhalt und Ergebnis; Zweck eigentlich Argumentationssegmentierung. Arbeitsrecht-Anteil unklar. Erwähnt in https://arxiv.org/pdf/2110.00806v1.pdf
- **Berger/Neugart** (Ökonometrie, keine Vorhersage): Erfolgschancen von Arbeitnehmern hängen u. a. von Arbeitnehmermerkmalen, lokalem Arbeitsmarkt und Gerichtsbesetzung ab. https://econpapers.repec.org/RePEc:bpj:germec:v:13:y:2012:i:1:p:56-70
- Ein experimentelles HF-Modell (ca. 2.800 deutsche Fälle, Gewinner aus Sachverhalt) existiert, ohne belastbare Evaluation: https://huggingface.co/LennardZuendorf/legalis-BERT
- Kein deutsches Kündigungsschutz-LJP-Paper gefunden. Das heißt nicht, dass keines existiert.

## 2. Fallstricke und glaubwürdiges Protokoll

- **Label-Leakage durch Post-hoc-Text**
  - Preprint zu UK Employment Tribunal: Training nur auf ca. 4 % Leakage-Features liefert hohe Leistung; Masking senkt Macro-F1 kaum. https://arxiv.org/pdf/2607.04261
  - Kritik: nur 12 von 171 Papers sagen tatsächlich Entscheidungen voraus, viele nutzen den Urteilstext. https://arxiv.org/pdf/2402.01656
  - Labelnamen im Input: https://arxiv.org/pdf/2605.29738
  - Für Deutschland (ohne Quelle): Tatbestand enthält oft Prozessgeschichte, Anträge und Formulierungen wie "streitig"/"unstreitig", die das Ergebnis nahelegen. Vergleichs-/Rücknahme-Verfahren haben keinen echten Tenor.
- **Zufällige Splits** unterschätzen Drift; zeitlicher Split ist Standard (SJP, https://arxiv.org/pdf/2605.24452).
- **Gericht/Region/Richter als Confounder:** Erfolgschance hängt von Ort und Zeit ab (Berger/Neugart, s. o.). Gegenmaßnahme: Gerichtsname maskieren, Gericht-only-Baseline mitführen, gruppierte Splits.
- **Klassenungleichgewicht:** Macro-F1 plus Majority-Baseline; "teilweise" als eigene Klasse ist bei Kündigungsschutz häufig Vergleich (ohne Quelle).
- **Duplikate:** Fassungen derselben Entscheidung, Serienverfahren, Parallelfälle der gleichen Parteien. Dedup über Aktenzeichen und Near-Duplicate-Hash, Split nach Gruppe.
- **Glaubwürdig:** Temporal Hold-out + Leakage-Ablation (Maskierung) + Trivial-Baselines + Konfidenzintervalle (Bootstrap).

## 3. Modelle auf CPU

- **TF-IDF + LogReg/linear-SVM:** Minuten, SJP nutzt es als Baseline. Auf LexGLUE-artigen Langtexten oft nur knapp hinter Transformern (Mamakas et al., https://aclanthology.org/2023.semeval-1.119.pdf betrifft Longformer + TF-IDF).
- **Hierarchisches BERT (gbert-base):** nur Embeddings extrahieren möglich; Feintuning auf 4 Kernen für zehntausende Dokumente zu langsam (Einschätzung, ohne Quelle).
- **Longformer:** auf CPU nicht praktikabel für Training.
- **Erwartete Spannen** (ohne Quelle, Schätzung): zeitlicher Split ohne Leakage-Maskierung 0,60-0,70; nach Maskierung und Dedup realistisch 0,50-0,60 bei Mehrklassen. SJP-Referenz 68-70 % (binär, anderes Gericht).

## 4. Regulierung

- **AI Act Anhang III Nr. 8(a):** Systeme, die eine Justizbehörde bei Recherche/Auslegung/Anwendung von Recht auf Fakten unterstützen, sind Hochrisiko. https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3
- Rein administrative Hilfsaufgaben (u. a. Anonymisierung) sind nach Erwägungsgrund 40 ausgenommen; Profiling hebt die Art.-6(3)-Ausnahme auf. https://ai-act-service-desk.ec.europa.eu/de/node/468
- Anwaltstool für Parteien fällt nach meiner Lesart nicht unter 8(a), da keine Justizbehörde; die Anwendbarkeit auf Ausgangsprognosen ist offen (ohne Quelle, rechtlich prüfen). CCBE sieht Auslegungsunklarheit: https://www.ccbe.eu/fileadmin/speciality_distribution/public/documents/IT_LAW/ITL_Position_papers/EN_ITL_20250920_CCBE-response-to-the-targeted-stakeholder-consultation-on-the-implementation-of-the-AI-Act-s-rules-for-high-risk-AI-systems_1.pdf
- **Fristen:** Laut Berichten verschiebt das Digital Omnibus Annex-III-Pflichten auf 2.12.2027, final laut Orrick Juli 2026 (gegen Amtsblatt prüfen). https://www.orrick.com/en/Insights/2026/07/EU-AI-Act-Update-Digital-Omnibus-Finalizes-8-Compliance-Changes
- **RDG:** BGH hält schematische Vertragsgeneratoren für zulässig (Smartlaw, https://www.lto.de/recht/juristen/b/bgh-urteil-izr11320-vertragsgenerator-smartlaw-keine-unzulaessige-rechtsdienstleistung-rak-hamburg-rdg-legal-tech); individuelle KI-Rechtsauskunft gegenüber Verbrauchern bleibt offen. https://www.beck-aktuell.de/rechtsbranche/legal-tech-digitalisierung/chatgpt-individuelle-rechtsberatung-ki-jura-rechtsdienstleistung-2025-11-11
- **Anwälte vs. Verbraucher:** Ein Prognosewerkzeug für Anwälte (Entscheidungshilfe, Anwalt bleibt verantwortlich) ist rechtlich einfacher; ein Verbraucherangebot mit Erfolgsprognose zum Einzelfall riskiert eine Rechtsdienstleistung nach § 2 RDG (ohne Quelle).

## 5. Minimales Experimentdesign

- **Daten:** Kündigungsschutz-Fälle (Arbeitsgerichte, LAG) aus openlegaldata filtern. Datensatz ist gated (https://huggingface.co/datasets/openlegaldata/court-decisions-germany); die sektionierte Variante https://huggingface.co/papers/2601.01449 (251.038 Entscheidungen, Tenor/Tatbestand/Gründe getrennt) spart Eigenparsing.
- **Label:** regelbasiert aus Tenor (stattgegeben / abgewiesen / teilweise); Vergleich, Rücknahme, Unklares verwerfen; manuelle Stichprobe (n ≈ 100) zur Labelqualität.
- **Eingabe:** nur Tatbestand; Maskierung von Gericht, Aktenzeichen, Namen, Datums-/Betragsangaben; Leakage-Ablation mit Entfernen der Prozessgeschichte und Satzmustern nach dem Urteil.
- **Splits:** zeitlich (Train bis T1, Val T1-T2, Test ab T2); Gruppierung nach Aktenzeichen-Cluster; Dedup vorab.
- **Baselines:** Majority; Gericht-only; Jahr-only; TF-IDF + LogReg (Wort- und Zeichen-n-Gramme); optional gbert-Embeddings + LogReg.
- **Metriken:** Macro-F1 (primär), pro-Klasse-Recall, Balanced Accuracy; Bootstrap-95-%-KI; Kalibrierung (Brier). Vorhersage nur dann nützlich, wenn sie Gericht-only und Majority signifikant schlägt.
