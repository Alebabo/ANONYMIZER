# Cato — Kontext: Idee und Vision

Kurzkontext für Menschen und KI-Assistenten, die an Cato arbeiten. Stand: 2026-11-15.

Quellenlage:
- **Positionierung:** vom Gründer vorgegeben. Cato ist allgemeine Anonymisierung für KI, Legal ist ein Teilbereich.
- **Funktionen, Prinzipien, Stand:** aus README und `docs/` übernommen. Diese Texte sind noch auf Legal ausgerichtet (siehe "Lücke zwischen Zielbild und Code").
- **Vision im Detail und Risiken:** abgeleitet, bitte korrigieren.

## Kurzfassung

- Cato ist **Anonymisierungs-Infrastruktur für KI**.
- Cato erkennt, klassifiziert, anonymisiert und kontrolliert sensible Informationen, **bevor** ein KI-Modell oder Agent sie verarbeitet.
- Cato ist eine Komponente, die andere Produkte und interne KI-Anwendungen einbauen. Cato ist selbst keine Fachanwendung.
- **Legal ist ein Teilbereich**, nicht die Definition des Produkts. Es ist die erste Domäne, die Cato tief abdeckt.
- Self-hosted, Apache-2.0, Sprachen DE und EN.
- Der funktionale Kern ist implementiert und auf synthetischen Daten getestet. Auf echten Dokumenten ist Cato nicht validiert, und es ist keine Compliance-Zertifizierung.

## Problem

- Organisationen wollen LLMs nutzen. Die besten Modelle laufen bei externen Cloud-Anbietern.
- Ihre Texte enthalten Daten, die dort nicht ungeschützt hingehören:
  - personenbezogene Daten und Kontaktdaten
  - Identifikatoren und Finanzdaten (Steuer-ID, IBAN, Kartennummern)
  - besondere Kategorien und Strafdaten (Art. 9/10 DSGVO)
  - Berufs- und Geschäftsgeheimnisse
- Wie kritisch ein Wert ist, hängt vom Kontext ab. Derselbe Name ist in einem Beispieltext unkritisch und in einer Patienten-, Personal- oder Mandantenakte kritisch.
- Wenn ein LLM selbst entscheidet, was geschwärzt wird, ist die Entscheidung nicht reproduzierbar und nicht prüfbar.
- Agenten verschärfen das Problem: sie lesen Dateien und rufen Tools auf, ohne dass ein Mensch jeden Text vorher sieht.

## Idee

Eine deterministische Schutzschicht zwischen Daten und Modell:

1. **Detect:** Regeln mit Prüfsummen plus spaCy NER, dazu Kontextsignale.
2. **Classify:** Risiko `low` / `sensitive` / `critical` pro Entität und Dokument, jede Stufe mit Begründung.
3. **Policy:** versionierte YAML-Policies entscheiden pro Entität und Ziel (`external` oder `local`):
   - anonymisieren (Methode pro Typ)
   - `review` (menschliche Freigabe)
   - `local_only` (nur lokales Modell)
   - `block`
4. **Anonymize:** konsistente Platzhalter (`PERSON_001`), damit das Modell den Text noch versteht. Das Mapping liegt verschlüsselt im Vault, getrennt vom Schlüssel.
5. **Restore:** Originalwerte werden nur innerhalb der vertrauenswürdigen Umgebung wieder eingesetzt.
6. **Trace & Audit:** jede Entscheidung ist nachvollziehbar, gespeichert werden nur Metadaten.

Kernaussage: Das Modell arbeitet mit Platzhaltern, die Organisation behält die Identitäten.

## Aufbau: Kern und Domänen

| Ebene | Inhalt | Beispiele |
|---|---|---|
| Kern (domänenneutral) | Erkennung allgemeiner Typen, Klassifikation, Policy-Engine, Anonymisierung, Vault, Gateway, MCP, Traces, Audit | Person, Organisation, Adresse, E-Mail, Telefon, IBAN, Kreditkarte, Steuer-ID, Gesundheitsdaten |
| Domäne Legal (vorhanden) | Juristische Typen, Verfahrensrollen, Kontextsignale, Standard-Policy | Aktenzeichen, Gerichte, Zitate, Privilege-Marker, Rollen wie Mandant oder Beschuldigter, Policy `legal-default` |
| Weitere Domänen (nicht vorhanden) | Eigene Typen, Signale und Policies pro Branche | Gesundheit, HR, Finanzen, öffentliche Verwaltung |

Eigene Entitätstypen lassen sich heute schon per Konfiguration ergänzen (`custom_entities`), eigene Policies per YAML.

## Integrationswege

| Weg | Zweck |
|---|---|
| Gateway `POST /v1/chat/completions` | OpenAI-kompatibler Drop-in. Nur Base-URL und Key ändern sich |
| REST API | `scan`, `classify`, `anonymize`, `protect`, `restore`, Dokumente (DOCX, PDF-Text) |
| Python SDK `cato-sdk` | Client für die API |
| MCP-Server `cato-mcp` | Agenten (Claude, Cursor) lesen Dateien nur anonymisiert |
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
- **Ehrliche Grenzen:** Cato liefert technische Schutzmaßnahmen. Es garantiert weder DSGVO-Konformität noch die Einhaltung von Berufsgeheimnissen.

## Vision

- **Zielbild:** Cato ist die Standard-Schutzschicht, über die sensible Daten in KI-Systeme fließen, unabhängig von der Branche.
- **Ein Kern, viele Domänen:** dieselbe Pipeline für alle. Branchenwissen kommt als Domäne dazu (Typen, Signale, Policies). Legal ist die erste.
- **Nutzenversprechen:** Organisationen können leistungsfähige externe Modelle einsetzen, ohne Identitäten und Geheimnisse preiszugeben, und können das gegenüber Kunden und Aufsicht belegen.
- **Routing statt Verbot:** was extern nicht darf, geht an ein lokales Modell oder in die Freigabe. Die Policy legt fest, welche Daten welches Modell sehen darf.
- **Agenten-tauglich:** Schutz gilt nicht nur für Chat-Prompts, sondern auch für Dateizugriffe und Tool-Aufrufe von Agenten.
- **Vertrauen durch Offenheit:** Open Source und Self-Hosting, damit die Schutzschicht selbst prüfbar ist und keine weitere Stelle Rohdaten sieht.

## Abgrenzung

Cato ist nicht:
- eine Fachanwendung (Vertragsanalyse, Recherche, Dokumentenerstellung)
- ein eigenes LLM
- eine Compliance-Zertifizierung oder Rechtsberatung
- ein Schutz für Inhalte, die an Cato vorbei ins Modell gelangen (z. B. Copy-Paste in den Chat)

## Lücke zwischen Zielbild und Code

Der Code ist heute ein Legal-Produkt mit allgemein nutzbarem Kern:

- **Texte und Branding:** README ("Privacy Infrastructure for Legal AI"), API-Beschreibung, MCP-Server-Anweisungen und Dashboard-Texte nennen Legal als Zweck.
- **Einzige eingebaute Policy** ist `legal-default`. Eine neutrale Standard-Policy fehlt.
- **Juristisches Wissen ist fest verdrahtet:** Rollen, Signale und Typen liegen im selben Code wie die allgemeinen Recognizer. Einen Mechanismus für Domänenpakete gibt es nicht.
- **Klassifikationsregeln** nutzen juristische Signale (`client_relationship`, `criminal_proceeding`) als Hauptkriterien für `critical`.
- **Testkorpus** besteht aus juristischen Texten (Arbeitsrecht, Strafverfahren, NDA, Litigation). Für andere Textarten gibt es keine Qualitätsaussage.

## Stand und Roadmap

Roadmap laut README, noch aus der Legal-Positionierung:

| Phase | Erledigt | Offen |
|---|---|---|
| 1 | Detection, Classification, Anonymisierung + Vault, Policies, REST API, Docker | Validierung auf echten Dokumenten |
| 2 | Gateway, MCP, Dokumente, Python SDK | Streaming, TypeScript SDK, nativer Anthropic-Endpoint |
| 3 | Traces, Metriken, Dashboard auf Live-Daten, API-Key-Verwaltung | Review-Queue mit Freigaben, grafischer Policy-Editor |
| 4 | Organisationen, Login, Rollen, Audit-Log mit Hash-Kette | SSO/MFA, feineres RBAC, PostgreSQL, Helm |

Für die allgemeine Positionierung fehlt zusätzlich (noch nicht in der Roadmap):
- Domänen als austauschbare Pakete, Legal als erstes
- neutrale Standard-Policy
- Korpus und Evaluation für nicht-juristische Texte
- Umstellung von README, Doku und UI-Texten

## Offene Fragen und Risiken

- **Differenzierung.** Allgemeine Anonymisierung für LLMs ist ein besetztes Feld (nicht recherchiert, aus Vorwissen): Microsoft Presidio als Open-Source-Standard, kommerzielle Anbieter wie Private AI, Skyflow und Nightfall, dazu DLP-Funktionen der Cloud-Anbieter. Die juristische Tiefe war bisher das Unterscheidungsmerkmal. Ohne sie braucht Cato ein anderes: z. B. deterministische Policies mit Audit, Routing auf lokale Modelle, Schutz für Agenten.
- **Breite gegen Tiefe.** Jede Domäne braucht eigene Typen, Signale, Korpora und Validierung. Ein kleines Team kann eine Domäne gut abdecken, nicht fünf.
- **Erkennungsqualität ist die harte Grenze.** Ein Wert, den die Detection übersieht, geht im Klartext raus. Der Leak-Check findet nur erkannte Werte. Recall-Zahlen auf echten Dokumenten fehlen, für nicht-juristische Texte auch auf synthetischen.
- **Pseudonymisierte Daten bleiben personenbezogen** (DSGVO, Erwägungsgrund 26). Cato senkt das Risiko, ersetzt aber keine AVV. Der Kontext kann Personen auch ohne Namen identifizierbar machen.
- **Zielkunde ist offen.** Entwickler und Produktteams (Infrastruktur, Self-Service) oder Endorganisationen wie Kanzleien (Dashboard, Login)? Das sind verschiedene Vertriebswege und Kaufentscheider.
- **Geschäftsmodell ist nicht definiert.** Apache-2.0 ohne festgelegte Monetarisierung (Hosting, Enterprise-Features, Support).
- **Substitution:** Anbieter mit EU-Hosting oder Zero-Data-Retention und lokale Modelle können den Umweg über Anonymisierung überflüssig machen.
- **Beschaffungshürden:** SSO/MFA und PostgreSQL fehlen. Fehlendes Streaming blockiert Chat-Oberflächen.

## Weiterführend

- Überblick und Quickstart: [README.md](README.md)
- Details: [docs/](docs/) (`detection`, `classification`, `anonymization`, `policies`, `gateway`, `mcp`, `accounts`, `API`)
