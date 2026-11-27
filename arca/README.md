# Arca (Prototyp)

Duale Datenbank: Originaldaten bleiben in **vault.db (B, vertraulich)**. Claude liest ausschließlich
**visible.db (A, KI-sichtbar)**, die nur nach expliziter Freigabe und nur anonymisiert befüllt wird.
Die Anonymisierung nutzt die vorhandene Erkennung (Cato 1.1, Regeln) und die Engine aus `packages/core`.

## Architektur

```
 vault.db (B)                         Arca-Service :8100 (127.0.0.1)            visible.db (A)
 ┌──────────────┐  Spalten wählen   ┌─────────────────────────────┐  Freigeben  ┌──────────────┐
 │ mandate      │ ────────────────▶ │ Cato-Erkennung + Engine     │ ──────────▶ │ mandate      │
 │ token_map    │ ◀──── Mapping ─── │ HMAC-Tokens (ARCA_SECRET)   │  + Leak-    │ (nur frei-   │
 │ preview      │ ◀──── Vorschau ── │ Vorschau (nicht freigegeben)│   Prüfung   │  gegebene    │
 │ audit_log    │ ◀──── Audit ───── │                             │             │  Spalten)    │
 └──────────────┘                   └─────────────────────────────┘             └──────┬───────┘
                                                                                       │ nur lesend
                        Dashboard-Tab "Arca" (Next.js)                                 ▼
                        ┌──────────────────────────────┐              ┌──────────────────────────┐
                        │ B | A, Anonymisieren,        │  WebSocket   │ arca/mcp/server.py       │
                        │ Freigeben, Terminal (xterm)  │ ───────────▶ │ list_tables, describe_   │
                        └──────────────────────────────┘  :8101       │ table, query (SELECT)    │
                                                         node-pty     └────────────┬─────────────┘
                                                         claude --tools ""         │ MCP (stdio)
                                                         --strict-mcp-config ──────┘
```

B → Cato → Vorschau → **Freigabe** → A → MCP → Claude. Claude hat vollen Lesezugriff auf A (alle freigegebenen
Tabellen und Spalten, beliebige SELECT-Abfragen, Blättern mit LIMIT/OFFSET) und keinen Zugang zu B.

## Dokumente und OCR

"Dokument hinzufügen" nimmt PDF, Scans, Bilder (PNG/JPEG/TIFF), DOCX und Text pro Mandat an. Scans liest
Tesseract (Deutsch) lokal über `anonymizer.ocr` aus packages/core:

- strikt offline: Eingabe nur per stdin, keine temporären Dateien, minimale Umgebung, Tesseract läuft in einem
  Netzwerk-Namespace ohne Netz (`unshare --net`). Arca verlangt diese Isolation; ohne sie wird kein Scan gelesen.
- gespeichert wird nur der Text (plus Dateiname, Format, SHA-256) in vault.db, nicht die Datei.
- der Text erscheint in Spalte "Dokumente" und geht wie jeder Freitext erst über Vorschau und Freigabe nach A.

Installation: `apt-get install tesseract-ocr tesseract-ocr-deu` und `pip install -e "packages/core[ocr]"`. Zurückübersetzen (Token → Klarname) läuft nur im
Service und wird nur in der UI angezeigt.

## Start

Voraussetzungen: Python 3.11+, Node 22, `claude`-CLI (angemeldet), Cato-Gewichte per `git lfs pull`.

```bash
pip install -e "packages/core[dev]" -e "arca[dev]"
```

```bash
cp arca/.env.example arca/.env && python -c "import secrets; print('ARCA_SECRET=' + secrets.token_hex(32))" >> arca/.env
```

```bash
npm ci && npm --prefix arca/terminal ci
```

Drei Prozesse (je ein Terminal):

```bash
arca-service
```

```bash
npm --prefix arca/terminal start
```

```bash
npm run dev
```

Dann http://localhost:3000/arca öffnen. vault.db wird beim ersten Start mit fiktiven Demo-Mandaten gefüllt,
visible.db leer angelegt (beides in `arca/data/`, gitignoriert).

Konfiguration: `ARCA_DATA_DIR`, `ARCA_API_URL` (Dashboard → Service), `NEXT_PUBLIC_ARCA_TERMINAL_URL`,
`ARCA_TERMINAL_PORT`, `ARCA_ALLOWED_ORIGINS`, `ARCA_CLAUDE_BIN`, `ARCA_PYTHON`.

## Betrieb auf dem Server

Deploy über `.github/workflows/deploy.yml` (bei grüner CI auf main): Image `deploy/arca.Dockerfile` (Ubuntu 24.04,
Tesseract, Cato, claude-CLI) wird in GitHub Actions gebaut und geladen, Container `arca` in
`deploy/docker-compose.prod.yml`. Erreichbar unter https://openanonymizer.tma-it-solution.de/arca
(cato.tma-it-solution.de/arca leitet dorthin weiter, siehe Repo tma-it-solutions, `vercel.json`).

- **Login:** Seite und alle Aktionen prüfen die Dashboard-Sitzung bei der API (`/v1/auth/me`), der
  Terminal-WebSocket (`/arca/terminal`, über Caddy) ebenso, plus Origin-Prüfung.
- **Eigenes Claude-Abo:** kein API-Key auf dem Server; `ANTHROPIC_*` wird aus Claudes Umgebung entfernt. Jede
  Person meldet sich im Terminal einmal mit ihrem Claude-Konto an; die Anmeldung liegt in einem eigenen
  Verzeichnis pro Dashboard-Nutzer (Volume `arca-claude`).
- **Vereinfachte Abschottung (bewusst gewählt):** Service, Terminal und Claude laufen in einem Container mit
  gemeinsamem Datenverzeichnis; die Trennung B/A hängt am Code (keine Built-in-Tools, MCP nur auf visible.db),
  nicht an Volumes. OCR läuft lokal im Container, aber ohne eigene Netztrennung (Docker erlaubt kein unshare).
- `ARCA_SECRET` legt der Deploy einmalig in der Server-`.env` an. Sichern: ohne ihn ändern sich alle Tokens.
- Ein Datenbestand für alle angemeldeten Personen (keine Trennung nach Organisation).

## Komponenten

| Pfad | Aufgabe |
|---|---|
| `src/arca/vault_db.py` | Schema und Seed von vault.db, Spaltenarten (Person, Firma, Partei, Aktenzeichen, Ort, Betrag, Freitext) |
| `src/arca/tokens.py` | `ArcaVault`: Vault-Protocol der Engine, Token = `TYP_` + 8 Hex aus HMAC-SHA256(ARCA_SECRET, Wert) |
| `src/arca/anonymize.py` | Spaltenweise Vorschau: strukturierte Spalten fail closed als ganzer Wert, Freitext mit Cato plus bekannten Werten aller Zeilen |
| `src/arca/release.py` | Freigabe (visible.db atomar neu aufbauen), unabhängige Leak-Prüfung, Widerruf, Audit-Log |
| `src/arca/service.py` | lokale HTTP-API für Dashboard und Terminal |
| `mcp/server.py` | eigenständiger MCP-Server: nur `sqlite3` + `mcp`, nur `visible.db`, `mode=ro`, SQLite-Authorizer (kein ATTACH/PRAGMA/Schreiben) |
| `terminal/server.mjs` | WebSocket + node-pty, startet `claude` nur nach Freigabe, beendet die Sitzung bei Widerruf |
| `app/(app)/arca/` | Dashboard-Tab |

## Tests

```bash
cd arca && python -m pytest -q
```

```bash
npm --prefix arca/terminal test
```

Abgedeckt: MCP-Server kann vault.db weder öffnen noch per ATTACH erreichen, importiert nichts aus Arca und
liest keine Umgebungsvariablen; nur SELECT; visible.db ohne Freigabe leer; nach Freigabe kein Originalname,
keine Firma, kein Aktenzeichen und kein Ort aus dem Seed in visible.db; gleiche Werte ergeben gleiche Tokens
(auch nach Neuaufbau); Freigabe stoppt bei Restwerten; Audit-Log; claude startet ohne Built-in-Tools.

## Bekannte Grenzen

- **Rückschluss aus Kontext im Freitext**: Branche, Rolle, Datum und Streitwert bleiben lesbar
  ("Geschäftsführer", "Röntgengerät", "12.03.2022", "500.000 €"). Bei kleinen Beständen oder bekannten
  Verfahren reicht das zur Re-Identifizierung. Daten und Beträge werden bewusst nicht vergröbert.
- **Erkennungslücken**: Freitext ist nur so gut wie Cato (Firmen-Recall auf LER ca. 0,54). Namen, die in keiner
  strukturierten Spalte stehen und die Cato übersieht, gehen durch. Die Leak-Prüfung findet nur bekannte Werte.
- **OCR**: Erkennungsfehler ("Mustermarm") können Namen an Cato vorbeischleusen; Handschrift und schlechte
  Scans werden schlecht gelesen. Die Vorschau vor der Freigabe ist deshalb Pflicht, nicht Formsache.
  Bekanntes Beispiel (Test `test_known_gap_location_in_scan`): "Zeuge ... aus Lüneburg" lässt den Ort stehen;
  das ist eine Lücke von Cato, nicht vom OCR.
- **Deterministische Tokens**: wer ARCA_SECRET hat, kann zu einem geratenen Namen das Token berechnen.
  Der Schlüssel gehört nicht neben die Daten (Produktiv: KMS/HSM). 8 Hex-Zeichen sind für einen Prototyp
  genug; Kollisionen werden erkannt und abgelehnt, nicht aufgelöst.
- **Gleiche Werte über Spalten**: Tokens hängen nur vom Wert ab, so lassen sich Mandate über A verknüpfen
  (gewollt für Auswertungen, aber ein Pseudonym, kein anonymes Datum im Sinne der DSGVO).
- **Claude-CLI**: Schutz beruht auf `--tools ""`, `--strict-mcp-config` und `--setting-sources project`.
  Eine Person am Terminal kann mit `!befehl` selbst Shell-Befehle ausführen, deren Ausgabe in den Kontext
  geht. Das ist eine Bedienerhandlung, keine Claude-Fähigkeit; für den Produktivbetrieb Claude in einem
  Container/Benutzer ohne Leserechte auf vault.db starten.
- **Dateirechte**: der MCP-Server prüft nur den Dateinamen `visible.db`. Eine als visible.db umbenannte
  Kopie von vault.db würde er lesen. Die echte Grenze sind getrennte Verzeichnisse und Betriebssystemrechte.
- **Kein Login/keine Mandantentrennung** im Arca-Service; er lauscht nur auf 127.0.0.1. Im Live-Modus schützt
  die Dashboard-Middleware die Seite, nicht den Service selbst.
- Was Claude über MCP liest, geht an Anthropic. Das ist der Zweck, aber eben nur für freigegebene Daten.
