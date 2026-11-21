# Hinweise für Coding-Agents

Aktueller Projektstand, Messwerte, laufende Branches und nächste Schritte: **[STATUS.md](STATUS.md)**. Zuerst lesen.

Arbeitsregeln:

- Python: `packages/core` (`pip install -e ".[dev]"`, spaCy `de_core_news_lg` und `en_core_web_lg` 3.8.0), Tests mit `pytest`.
- Dashboard: Next.js im Repo-Root, Typecheck `npx tsc --noEmit -p .`.
- Vor jedem Commit auf main: alle Tests grün, Typecheck grün.
- Änderungen an der Erkennung (`packages/core/src/anonymizer/detect/`) immer messen:
  `python packages/core/scripts/ler_data.py eval --split test`, `python packages/core/scripts/court_data.py eval --split test`
  und `python packages/core/scripts/finance_data.py eval`.
  Nur übernehmen, wenn Präzision und Personen-Recall nicht sinken.
- Keine echten Kunden- oder Mandantendaten committen oder an Cloud-Dienste senden; firmenspezifisches unter `local/` (gitignoriert).
- Modellgewichte über Git LFS (`models/**/model`); Datenlizenzen in `THIRD_PARTY_NOTICES.md` pflegen.
- Dokumentation und Kommunikation mit dem Projektinhaber auf Deutsch, sachlich, ohne Emojis.
