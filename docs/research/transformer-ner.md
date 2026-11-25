# Transformer statt CNN als deutsche NER (Experiment)

Stand: 25.11.2026, Branch `feature/transformer-ner`. Ergebnisse stehen noch aus (Training auf GPU).

## Frage

Cato 1.1 ist eine spaCy-Pipeline mit CNN-Tok2Vec (Breite 96, Tiefe 4, 20.000 Vektorzeilen). Drei weitere
Trainingsläufe hoben den Firmen-Recall nicht (LER-Test 0,52, Ziel ≥ 0,65 bei Präzision ≥ 0,90,
`org-ner-results.md`). GLiNER scheiterte zero-shot an der Abgrenzung Firma/Behörde (`gliner-results.md`); das
spricht nicht gegen ein **feinjustiertes** Transformer-Modell, das dieselben Labels und Konventionen lernt wie Cato.

Frage: Hebt ein feinjustierter deutscher Encoder (`deepset/gbert-base`, MIT, 110 M Parameter) Firmen- und
Personen-Recall, ohne Präzision zu verlieren, auf denselben Daten und mit denselben Regeln?

## Aufbau

- `packages/core/scripts/tf_train.py`: Token-Klassifikation (BIO für PER, ORG, LOC, MISC). Daten kommen aus
  `ner_train.collect()`, also exakt der Cato-Mix (LER, Gerichtsentscheidungen, GermEval, MultiCoNER,
  `datasets/public`, synthetische Support-Texte); fehlende Tokens („-“) bleiben aus dem Loss. Tokenisierung mit
  Cato, damit Training und Laufzeit dieselben Wörter sehen. Modellauswahl wie bei Cato auf LER dev mit der kompletten
  Pipeline.
- `packages/core/src/anonymizer/detect/hf_ner.py`: tauscht in der Cato-Pipeline nur die Komponente `ner`.
  Tagger, Morphologizer und alle Regeln danach (Behörden, Bereinigung, Unterschriftszeilen, Chat) bleiben gleich;
  die Messung vergleicht also nur die NER. Aktivieren: `ANONYMIZER_NER_MODEL_DE="<cato-1.1>+<hf-ordner>"`.
  Lange Texte in Fenstern von 512 Subwords mit 128 Überlappung; je Wort zählt das Fenster, in dem es am weitesten
  vom Rand liegt.
- Neue öffentliche Trainingsdaten (Hugging Face, `datasets/public/README.md`): nobody-pii-synth-de (Apache-2.0),
  nym-pii-multilingual-data DE-Teil (MIT), medical-pii-multilingual DE (Apache-2.0).
- `notebooks/tf_train_kaggle.ipynb`: Training und Messung auf Kaggle/Colab-GPU.

## Aufwand

Voller Datenmix: 45.860 Beispiele, 54.689 Fenster à höchstens 256 Subwords, 6,7 Mio. Subword-Tokens. Laptop-CPU
(i5-1145G7, 4 Kerne): ca. 10 s pro Schritt (Batch 16), 3.419 Schritte pro Epoche, also ca. 9,5 h pro Epoche.
Darum Training auf GPU.

Nach 100 Schritten (3 % einer Epoche, CPU) LER-dev-F1 0,496 auf 100 Dokumenten: nur ein Funktionstest, kein Ergebnis.

## Abnahme

Wie bei Cato (AGENTS.md, STATUS.md): Test-Splits mit `ler_data.py`, `court_data.py`, `finance_data.py`,
`public_pii.py`; übernehmen nur, wenn Präzision und Personen-Recall nicht sinken. Zusätzlich messen: Latenz auf CPU
pro Dokument gegen Cato und Speicherbedarf (gbert-base ca. 420 MB in float32; ONNX/int8 als nächster Schritt).

## Offen

- Ergebnisse des GPU-Laufs eintragen.
- Bei Gewinn: CPU-Latenz senken (ONNX-Export mit int8, oder Destillation in ein kleineres Modell).
- Mehrere Seeds, bevor eine Übernahme entschieden wird.
