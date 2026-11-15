# Cato — Kontext: Idee und Vision

Kurzkontext für Menschen und KI-Assistenten, die an Cato arbeiten. Stand: 2026-11-15.

Quellenlage:
- **Idee, Prinzipien, Stand:** aus README und `docs/` übernommen.
- **Vision und Risiken:** aus Positionierung und Roadmap abgeleitet. Vom Gründer noch nicht bestätigt, bitte korrigieren.

## Kurzfassung

- Cato ist **Privacy-Infrastruktur für Legal AI**.
- Cato erkennt, klassifiziert, anonymisiert und kontrolliert sensible juristische Informationen, **bevor** ein KI-Modell oder Agent sie verarbeitet.
- Cato ist eine Komponente, die Legal-Tech-Produkte einbauen. Cato ist selbst keine Legal-Tech-Anwendung.
- Self-hosted, Apache-2.0, Sprachen DE und EN.
- Phase 1 (funktionaler Kern) ist implementiert und auf synthetischen Daten getestet. Auf echten Akten ist Cato nicht validiert, und es ist keine Compliance-Zertifizierung.

## Problem

- Kanzleien und Rechtsabteilungen wollen LLMs nutzen. Die besten Modelle laufen bei externen Cloud-Anbietern.
- Juristische Dokumente enthalten Daten, die dort nicht ungeschützt hingehören:
  - Mandatsgeheimnisse (§ 203 StGB, § 43a BRAO)
  - besondere Kategorien und Strafdaten (Art. 9/10 DSGVO)
  - Identifikatoren, Finanzdaten, Geschäftsgeheimnisse
- Generische PII-Filter kennen den juristischen Kontext nicht: Verfahrensrollen (Mandant, Beschuldigter, Zeuge), Aktenzeichen, Privilege-Marker. Derselbe Name ist in einem Lehrbeispiel unkritisch und in einem Strafverfahren kritisch.
- Wenn ein LLM selbst entscheidet, was geschwärzt wird, ist die Entscheidung nicht reproduzierbar und nicht prüfbar.

## Idee

Eine deterministische Schutzschicht zwischen Daten und Modell:

1. **Detect:** Regeln mit Prüfsummen plus spaCy NER, dazu Kontextsignale und Verfahrensrollen.
2. **Classify:** Risiko `low` / `sensitive` / `critical` pro Entität und Dokument, jede Stufe mit Begründung.
3. **Policy:** versionierte YAML-Policies entscheiden pro Entität und Ziel (`external` oder `local`):
   - anonymisieren (Methode pro Typ)
   - `review` (menschliche Freigabe)
   - `local_only` (nur lokales Modell)
   - `block`
4. **Anonymize:** konsistente Platzhalter (`PERSON_001`), damit das Modell den Text noch versteht. Das Mapping liegt verschlüsselt im Vault, getrennt vom Schlüssel.
5. **Restore:** Originalwerte werden nur innerhalb der vertrauenswürdigen Umgebung wieder eingesetzt.
6. **Trace & Audit:** jede Entscheidung ist nachvollziehbar, gespeichert werden nur Metadaten.

Kernaussage: Das Modell arbeitet mit Platzhaltern, die Kanzlei behält die Identitäten.

## Integrationswege

| Weg | Zweck |
|---|---|
| Gateway `POST /v1/chat/completions` | OpenAI-kompatibler Drop-in. Nur Base-URL und Key ändern sich |
| REST API | `scan`, `classify`, `anonymize`, `protect`, `restore`, Dokumente (DOCX, PDF-Text) |
| Python SDK `cato-sdk` | Client für die API |
| MCP-Server `cato-mcp` | Agenten (Claude, Cursor) lesen Akten nur anonymisiert |
| CLI `cato` | Lokale Nutzung, Evaluation, Administration |
| Dashboard (Next.js) | Traces, Metriken, Policies, API-Keys, Mitglieder, Audit-Log |

## Designprinzipien

- **Determinismus:** kein LLM entscheidet, ob kritische Daten weitergegeben werden.
- **Fail closed:**
  - Unbekannte Typen werden geschwärzt.
  - Unsichere Erkennungen werden nie herabgestuft.
  - Fehlt die NER, gibt es nie das Ergebnis `low`.
- **Critical Floor:** kritische Daten gehen nie unverändert an externe Modelle.
- **Keine Rohdaten** in Logs, Traces, Fehlermeldungen oder API-Antworten.
- **Re-Identifikation nur im Backend:** Restore braucht einen Admin-API-Key. Agenten und Dashboard-Sessions können nicht re-identifizieren.
- **Nachweisbarkeit:** Policy-Version und Hash an jeder Entscheidung, Audit-Log mit Hash-Kette.
- **Ehrliche Grenzen:** Cato liefert technische Schutzmaßnahmen. Es garantiert weder DSGVO-Konformität noch die Einhaltung der anwaltlichen Verschwiegenheit.

## Vision (abgeleitet)

- **Zielbild:** Cato ist die Standard-Schutzschicht, über die juristische Daten in KI-Systeme fließen. Legal-Tech-Anbieter bauen Schwärzung, Policies und Audit nicht selbst, sondern binden Cato ein.
- **Nutzenversprechen:** Kanzleien können leistungsfähige externe Modelle einsetzen, ohne Identitäten und Mandatsgeheimnisse preiszugeben, und können das gegenüber Mandanten, Kammer und Aufsicht belegen.
- **Routing statt Verbot:** was extern nicht darf, geht an ein lokales Modell oder in die Freigabe. Die Policy legt fest, welche Daten welches Modell sehen darf.
- **Agenten-tauglich:** Schutz gilt nicht nur für Chat-Prompts, sondern auch für Dateizugriffe und Tool-Aufrufe von Agenten.
- **Vertrauen durch Offenheit:** Open Source und Self-Hosting, damit die Schutzschicht selbst prüfbar ist und keine weitere Stelle Rohdaten sieht.

## Abgrenzung

Cato ist nicht:
- eine Anwendung für Vertragsanalyse, Recherche oder Schriftsatzerstellung
- ein eigenes LLM
- eine Compliance-Zertifizierung oder Rechtsberatung
- ein Schutz für Inhalte, die an Cato vorbei ins Modell gelangen (z. B. Copy-Paste in den Chat)

## Stand und Roadmap

| Phase | Erledigt | Offen |
|---|---|---|
| 1 | Detection, Classification, Anonymisierung + Vault, Policies, REST API, Docker | Validierung auf echten Dokumenten |
| 2 | Gateway, MCP, Dokumente, Python SDK | Streaming, TypeScript SDK, nativer Anthropic-Endpoint |
| 3 | Traces, Metriken, Dashboard auf Live-Daten, API-Key-Verwaltung | Review-Queue mit Freigaben, grafischer Policy-Editor |
| 4 | Organisationen, Login, Rollen, Audit-Log mit Hash-Kette | SSO/MFA, feineres RBAC, PostgreSQL, Helm |

## Offene Fragen und Risiken

- **Erkennungsqualität ist die harte Grenze.** Ein Name, den die Detection übersieht, geht im Klartext raus. Der Leak-Check findet nur erkannte Werte. Ohne Recall-Zahlen auf echten Akten ist das Sicherheitsversprechen nicht belegt.
- **Pseudonymisierte Daten bleiben personenbezogen** (DSGVO, Erwägungsgrund 26). Cato senkt das Risiko, ersetzt aber weder AVV noch die berufsrechtliche Prüfung. Der Kontext eines Falls kann Personen auch ohne Namen identifizierbar machen.
- **Zielkunde ist unscharf.** Das README adressiert Legal-Tech-Anbieter. Dashboard, Login und MCP-Doku adressieren Kanzleien direkt. Das sind zwei verschiedene Vertriebswege und Kaufentscheider.
- **Geschäftsmodell ist nicht definiert.** Apache-2.0 ohne festgelegte Monetarisierung (Hosting, Enterprise-Features, Support).
- **Wettbewerb und Substitution** (in dieser Datei nicht recherchiert):
  - generische PII-Tools, z. B. Microsoft Presidio
  - Anbieter mit EU-Hosting oder Zero-Data-Retention
  - lokale Modelle, die den Umweg über Anonymisierung überflüssig machen können
- **Beschaffungshürden:** SSO/MFA und PostgreSQL fehlen. Fehlendes Streaming blockiert Chat-Oberflächen.

## Weiterführend

- Überblick und Quickstart: [README.md](README.md)
- Details: [docs/](docs/) (`detection`, `classification`, `anonymization`, `policies`, `gateway`, `mcp`, `accounts`, `API`)
