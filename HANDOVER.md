# Übergabe: OpenAnonymizer testen, anpassen und betreiben

Stand: 21.11.2026. Diese Datei ist die Arbeitsanleitung, um OpenAnonymizer auf der Arbeit zu testen, an die eigene Umgebung anzupassen und später im Firmennetz zu betreiben. Aktueller Projektstand: [STATUS.md](STATUS.md), technische Referenz: [docs/API.md](docs/API.md) und [docs/mcp.md](docs/mcp.md).

Hinweis: Kundenchat-Zugriff (Conversations), Prompt-Verwaltung, das OpenAI-kompatible Gateway und der MCP-Proxy wurden im November 2026 entfernt (keine Oberfläche, weniger Angriffsfläche). Die frühere Fassung dieser Anleitung steht in der Git-Historie.

---

## 1. Kurzfassung

OpenAnonymizer erkennt, klassifiziert und pseudonymisiert personenbezogene Daten, **bevor** ein KI-Modell sie sieht. Ein Modell, drei Wege, alle in den Traces protokolliert (Kanal `api` | `mcp` | `dashboard`, Key/Nutzer):

| Weg | Wie |
|---|---|
| Dashboard-Chat | Text eingeben, sehen, was die KI bekäme; Erkennung korrigieren (Feedback) |
| REST | `POST /v1/protect`, `/v1/scan`, `/v1/anonymize`; Policy-Test `POST /v1/policies/{name}/test` |
| MCP | `/mcp` (HTTP, Bearer-Key), Tool `anonymize_content`; dazu die CSV-Uploads (`list_datasets`, `query_dataset`) |

```
Claude Code / Cursor (Laptop)
        │  MCP über HTTPS + persönlicher OpenAnonymizer-Key      ← nur Platzhalter-Daten
        ▼
OpenAnonymizer (Firmennetz)
   ├─ Erkennen → Klassifizieren → Policy → Pseudonymisieren
   ├─ CSV-Playground (Testdaten, Spalten ausblendbar)
   └─ Traces + Audit-Log (wer hat was getan, Inhalte nur mit ANONYMIZER_TRACE_CONTENT=1)
```

Nur mit **synthetischen** und öffentlichen Daten gemessen. Die Trefferquote auf euren echten Texten ist **unbekannt**.

---

## 2. Vor dem ersten Kontakt mit echten Daten (nicht überspringen)

| # | Punkt | Warum | Erledigt |
|---|---|---|---|
| 1 | **Freigabe von Security / Datenschutz** einholen | Ohne Freigabe ist ein selbstgebauter Datenschutz-Layer Schatten-IT. Gesprächsleitfaden: Abschnitt 10 | ☐ |
| 2 | **Vertrag mit Anthropic** klären (DPA, ggf. Zero Data Retention) | Auch pseudonymisierte Daten verlassen das Haus | ☐ |
| 3 | **Evaluation auf echter Stichprobe** (Abschnitt 6) | Erst messen, dann anschließen | ☐ |
| 4 | **Arbeitsvertrag / IP** klären | Wer besitzt Anpassungen aus der Arbeitszeit? Firmenspezifisches gehört nach `local/` oder in ein Firmen-Repo | ☐ |
| 5 | **Pro Person ein eigener API-Key** | Traces und Audit-Log hängen am Key | ☐ |

---

## 3. Lokal ausprobieren (Laptop, ca. 20 Minuten)

### 3.1 Installation

Voraussetzungen: Python ≥ 3.11, Git, Git LFS, ca. 2 GB Platz für die Sprachmodelle. Unter Windows: WSL oder Docker (Abschnitt 5).

```bash
git clone https://github.com/Alebabo/ANONYMIZER.git && cd ANONYMIZER
python -m venv .venv && source .venv/bin/activate
pip install -e "packages/core[dev]" -e sdk/python
git lfs pull && python -m spacy download en_core_web_lg   # German: Cato (Git LFS)
```

Hinter einem Firmen-Proxy: `pip` und der spaCy-Download brauchen `HTTPS_PROXY` und ggf. `REQUESTS_CA_BUNDLE`/`PIP_CERT` mit dem Firmen-CA-Zertifikat.

Kontrolle:

```bash
cd packages/core && python -m pytest -q && cd ../..
```

### 3.2 Server starten

```bash
export ANONYMIZER_API_KEYS=anonymizer_demo_key_change_me_0123456789
export ANONYMIZER_ADMIN_KEYS=anonymizer_demo_admin_change_me_0123456789
export ANONYMIZER_BOOTSTRAP_ADMIN_EMAIL=ich@example.org ANONYMIZER_BOOTSTRAP_ADMIN_PASSWORD=bitte-aendern-123
export ANONYMIZER_CUSTOM_PATTERNS=examples/support/patterns.yaml
export ANONYMIZER_MCP_HTTP=1
anonymizer-api
```

In jedem weiteren Terminal (Client-Seite):

```bash
export ANONYMIZER_API_KEY=anonymizer_demo_key_change_me_0123456789 ANONYMIZER_ADMIN_KEY=anonymizer_demo_admin_change_me_0123456789
```

Läuft auf `http://127.0.0.1:8080`. Die Daten (Vault, Policies, Traces, Audit, CSV-Uploads, Feedback) liegen in `./data/`.

```bash
curl -s localhost:8080/v1/protect -H "Authorization: Bearer $ANONYMIZER_API_KEY" -H 'Content-Type: application/json' \
  -d '{"text":"Unser Mandant Herr Max Mustermann bittet um Rückruf.","destination":"external"}'
```

### 3.3 Claude Code anbinden

```bash
claude mcp add --transport http anonymizer http://127.0.0.1:8080/mcp --header "Authorization: Bearer anonymizer_demo_key_change_me_0123456789"
```

Testfragen an Claude:

- „Anonymisiere diesen Absatz mit anonymize_content und fasse ihn dann zusammen: …“
- „Welche CSV-Datensätze gibt es? Zeig mir die ersten 5 Zeilen von …“ (nach einem Upload im Dashboard, 3.4)

### 3.4 Dashboard

Node.js ≥ 22:

```bash
npm ci && ANONYMIZER_API_URL=http://127.0.0.1:8080 npm run dev
```

Öffne `http://localhost:3000` und melde dich mit der Bootstrap-E-Mail und dem Passwort an.

- **Chat:** Text eingeben, geschützte Fassung sehen, falsche oder fehlende Erkennungen als Feedback markieren.
- **Traces:** jeder Aufruf über API, MCP, Chat oder CSV.
- **CSV:** Testdatei hochladen, Spalten ausblenden, Abfrage wie Claude sie bekommt.
- **Settings:** Policies (mit Test), API Keys, Members, Feedback (Export für das Nachtraining), Audit Logs.

---

## 4. Anpassen

### 4.1 Eigene Muster (Bestellnummern usw.)

Kopiere `examples/support/patterns.yaml` nach `local/patterns.yaml` (der Ordner `local/` ist gitignoriert) und passe die Regexe an eure Formate an:

```yaml
patterns:
  - name: order_number
    pattern: '\b[A-Z]{2}-\d{8}\b'        # z. B. DE-12345678
    confidence: 0.95
  - name: customer_number
    pattern: '\bK\d{7}\b'
    context_words: ['kunden', 'kd']
    confidence: 0.9
```

```bash
export ANONYMIZER_CUSTOM_PATTERNS=local/patterns.yaml
```

- Die Namen `customer_number`, `order_number`, `ticket_number`, `contract_number`, `invoice_number` und `tracking_number` werden von `support-default` **pseudonymisiert**: gleiche Nummer, gleicher Platzhalter.
- Jeder andere Name wird **geschwärzt**, oder du ergänzt eine Regel in deiner Policy (4.3).
- Eine ungültige Datei verhindert den Start. Das ist Absicht.

### 4.2 Was ist wo?

| Thema | Datei | Typische Anpassung |
|---|---|---|
| Erkennung eurer Nummern | `local/patterns.yaml` (`ANONYMIZER_CUSTOM_PATTERNS`) | Regex pro Format |
| Namen in Texten | `packages/core/src/anonymizer/detect/recognizers.py` → `SelfIntroductionRecognizer` | Weitere Einleitungen („Hier schreibt …“) |
| Falsch erkannte Wörter | `packages/core/src/anonymizer/detect/engine.py` → `NER_STOPWORDS`, oder `ANONYMIZER_KEEP_TERMS` | Wörter, die NER fälschlich als Namen markiert (z. B. euer Produktname) |
| Was wird wie behandelt | eigene Policy (4.3) | z. B. Gesundheitsdaten schwärzen statt zurückhalten |
| Spaltennamen als Hinweise (CSV) | `packages/core/src/anonymizer/result_filter.py` → `DEFAULT_FIELD_HINTS` | eigene Spaltennamen (`kunde_bezeichnung` …) |
| Anweisungen an Claude | `packages/core/src/anonymizer/mcp/server.py` → `INSTRUCTIONS`, Tool-Beschreibungen | Hausregeln |

Änderungen an der Erkennung immer messen (siehe `AGENTS.md`). Nach jeder Code-Änderung:

```bash
cd packages/core && python -m pytest -q
```

### 4.3 Eigene Policy

Nicht die eingebaute Datei ändern, sondern eine eigene Version hochladen (Dashboard: Settings → Policies, oder per API).

1. Kopiere `packages/core/src/anonymizer/policy/builtin/support-default.yaml` nach `local/support-firma.yaml` und setze `name: support-firma`.
2. Vorher testen (nichts wird gespeichert): `POST /v1/policies/dry-run` mit `candidate_yaml`, oder `POST /v1/policies/{name}/test` mit einzelnen Änderungen pro Typ.
3. Hochladen (Admin-Key):

```bash
python -c "import json; print(json.dumps({'yaml': open('local/support-firma.yaml').read()}))" | curl -s -X POST localhost:8080/v1/policies -H "X-API-Key: $ANONYMIZER_ADMIN_KEY" -H 'Content-Type: application/json' -d @-
```

4. Aktivieren: `ANONYMIZER_DEFAULT_POLICY=support-firma` (API, Chat, MCP) bzw. `ANONYMIZER_PLAYGROUND_POLICY=support-firma` (CSV). Server neu starten; ein unbekannter Name ist ein Startfehler.

### 4.4 API-Keys pro Person

```bash
curl -s -X POST localhost:8080/v1/api-keys -H "X-API-Key: $ANONYMIZER_ADMIN_KEY" -H 'Content-Type: application/json' -d '{"name":"alex-claude-code","role":"user"}'
```

Der Key wird **einmal** angezeigt und nur als Hash gespeichert. Alternativ im Dashboard unter API Keys. Dashboard-Nutzer: `anonymizer user create` oder Settings → Members.

---

## 5. Betrieb im Firmennetz

Erst nach Abschnitt 2 und der Evaluation (Abschnitt 6).

### 5.1 Docker Compose

```bash
cp .env.example .env
```

In `.env` setzen: Bootstrap-Admin, `ANONYMIZER_ADMIN_KEYS`, `ANONYMIZER_VAULT_KEY`, `ANONYMIZER_MCP_HTTP=1`, `ANONYMIZER_CUSTOM_PATTERNS=/config/patterns.yaml`. Werte erzeugen:

```bash
python -c "import secrets; print('anonymizer_' + secrets.token_urlsafe(32))"
python -c "from anonymizer.vault import VaultKey; print(VaultKey.generate().to_b64())"
```

In `docker-compose.yml` das Verzeichnis mit Patterns und Policy einhängen (`- ./local:/config:ro`), dann:

```bash
docker compose up -d --build
```

Beim Build hinter einem Firmen-Proxy braucht der Build das CA-Zertifikat: `docker build --secret id=ca_bundle,src=firmen-ca.crt ...` (siehe `docs/API.md`). Das Image ist mehrere GB groß (Sprachmodelle).

### 5.2 Netzwerk

- OpenAnonymizer lauscht nur auf `127.0.0.1:8080`. Davor gehört ein **Reverse Proxy mit TLS** (nginx, Traefik, euer Ingress), z. B. `https://anonymizer.firma.intern`.
- **Ausgehend** braucht OpenAnonymizer keinen Internetzugang.
- **Eingehend** nur aus dem Netz, in dem die Laptops sind (VPN). Nicht öffentlich.
- `ANONYMIZER_MCP_ALLOWED_HOSTS=anonymizer.firma.intern` aktiviert den Schutz gegen DNS-Rebinding.

Claude Code: `claude mcp add --transport http anonymizer https://anonymizer.firma.intern/mcp --header "Authorization: Bearer <persönlicher Key>"`. Claude Desktop und Konnektoren auf claude.ai brauchen OAuth; das ist noch nicht eingebaut.

### 5.3 Backups

- **`ANONYMIZER_VAULT_KEY` außerhalb des Servers sichern.** Ohne ihn ist der Vault (Platzhalter → echter Wert) nicht mehr lesbar.
- Das Volume `anonymizer-data` sichern: Vault, Policies, Accounts, Audit-Log, Traces, CSV-Uploads, Feedback.

---

## 6. Evaluation auf echter Stichprobe

Nur von einer **berechtigten Person im geschützten Bereich**, ohne Cloud-LLM. Ergebnisse und Stichproben bleiben in `local/`.

**Kanzleien (Schriftsätze, Mandantenmails):** Mess-Kit mit Schritt-für-Schritt-Anleitung für Nicht-Entwickler in [docs/local-eval.md](docs/local-eval.md) (`packages/core/scripts/local_eval.py`, ca. 30 Minuten, offline). Ergebnis ist ein Bericht nur mit Zahlen, der an das Entwicklerteam gehen kann.

1. 30–50 typische Texte auswählen, darunter bewusst schwierige: kleingeschrieben, Tippfehler, Adressen, Nummern.
2. Pro Text eine YAML-Datei in `local/korpus/` anlegen, Format wie `packages/core/tests/corpus/de_support.yaml`:

```yaml
id: chat-001
language: de
text: |
  hallo, hier ist frau schmidt-meier, meine bestellung DE-12345678 ...
expected:
  - {type: person, text: schmidt-meier}
  - {type: order_number, text: DE-12345678}
```

3. Auswerten:

```bash
ANONYMIZER_CUSTOM_PATTERNS=local/patterns.yaml anonymizer eval local/korpus
```

4. `recall` und `missed` festhalten, Patterns und Regeln nachziehen, wiederholen. Das Ergebnis (Recall, Restrisiko, Maßnahmen) dem Datenschutz vorlegen.

Bekanntes Verhalten:

- **Gut erkannt:** E-Mail, Telefon, IBAN, Adressen, Anrede plus Name („Frau Schmidt“), Selbstvorstellungen, eure Nummern mit Patterns.
- **Schwach:** **nackte Namen ohne Kontext**, kleingeschrieben („danke anna“). Das hängt an der NER und ist das größte Restrisiko.
- **Zu viel geschwärzt:** NER markiert in kleingeschriebenem Text normale Wörter als Namen. Kostet Lesbarkeit, nicht Datenschutz. Gegenmittel: `NER_STOPWORDS`, `ANONYMIZER_KEEP_TERMS`.

---

## 7. Konfiguration (wichtigste Variablen)

| Variable | Default | Empfehlung |
|---|---|---|
| `ANONYMIZER_DEFAULT_POLICY` | `banking-default` | für Kanzleien `legal-default`, sonst eigene Policy (4.3) |
| `ANONYMIZER_PLAYGROUND_POLICY` | `support-default` | Policy für CSV-Abfragen (früher `ANONYMIZER_CONVERSATIONS_POLICY`, wird noch gelesen) |
| `ANONYMIZER_CUSTOM_PATTERNS` | – | `local/patterns.yaml` |
| `ANONYMIZER_CATO_PATH` | `packages/core/models/cato-1.1` | Deutsches NER-Modell Cato 1.1 (einziges deutsches Modell) |
| `ANONYMIZER_MCP_HTTP` | 0 | `1` = MCP unter `/mcp` |
| `ANONYMIZER_MCP_ALLOWED_HOSTS` | – | eure OpenAnonymizer-Domain |
| `ANONYMIZER_VAULT_KEY` | – | **in Betrieb setzen**: stabile Platzhalter, Admin kann zurückübersetzen |
| `ANONYMIZER_API_KEYS` / `ANONYMIZER_ADMIN_KEYS` | – | Admin-Key nur für Policy und Restore; Personen-Keys über die API (4.4) |
| `ANONYMIZER_TRACE_CONTENT` | 0 | `1` nur mit Testdaten (speichert Originalwerte in Traces) |

Vollständige Liste: `.env.example` und `packages/core/src/anonymizer/api/settings.py`.

---

## 8. Fehlersuche

| Symptom | Ursache | Lösung |
|---|---|---|
| `401` auf `/mcp` | Key fehlt oder ist falsch | `claude mcp add ... --header "Authorization: Bearer <key>"` prüfen; `X-API-Key` geht auch |
| `/mcp` gibt 404 | `ANONYMIZER_MCP_HTTP` nicht gesetzt | `ANONYMIZER_MCP_HTTP=1`, neu starten |
| Start bricht ab mit Policy-Fehler | `ANONYMIZER_DEFAULT_POLICY` / `ANONYMIZER_PLAYGROUND_POLICY` existiert nicht | Policy hochladen (4.3) oder Name korrigieren |
| Start bricht ab mit Pattern-Fehler | Ungültiges YAML oder Regex in `ANONYMIZER_CUSTOM_PATTERNS` | Meldung nennt das Pattern |
| `NER disabled` in Warnungen | NER-Modelle fehlen | `git lfs pull` (Cato), `python -m spacy download en_core_web_lg` |
| Dashboard zeigt „Example data“ | `ANONYMIZER_API_URL` nicht gesetzt | `ANONYMIZER_API_URL=http://127.0.0.1:8080 npm run dev` |

---

## 9. Firmenspezifisches und Git

- **`local/`** ist gitignoriert: eigene Patterns, Policies, Korpus, Notizen. Echte Kunden- oder Mandantendaten gehören **nie** in ein Repo, auch nicht in ein privates.
- Generische Verbesserungen (bessere Erkennung, Bugfixes) können ins OpenAnonymizer-Repo; Firmenspezifisches ins Firmen-Repo.
- Entwicklungsablauf: Branch, `python -m pytest -q` in `packages/core`, für Dashboard-Änderungen `npx tsc --noEmit -p . && npx next build`. Die CI (`.github/workflows/ci.yml`) macht dasselbe plus `anonymizer eval tests/corpus`.

---

## 10. Leitfaden für das Gespräch mit Security / Datenschutz

**Was verlässt das Haus?**

- Nur Text, den die Policy erlaubt, und das pseudonymisiert. Namen, Kontaktdaten und eure Nummern werden zu Platzhaltern; Zahlungs- und Ausweisdaten werden geschwärzt.
- Texte mit besonderen Kategorien (Gesundheit u. a., Art. 9 DSGVO) werden je nach Policy zurückgehalten (`local_only`).

**Welche Kontrollen gibt es?**

- Persönliche Keys; sicherheitsrelevante Änderungen stehen im manipulationssicheren Audit-Log.
- Die Rückübersetzung von Platzhaltern geht nur mit Admin-Key im Haus und wird protokolliert.
- Policies sind deterministisch, versioniert und vorab testbar.
- Logs und Traces enthalten standardmäßig keine Inhalte.

**Was ist das Restrisiko?**

- Nicht erkannte Personendaten, vor allem nackte Namen. Gemessen durch die Evaluation (Abschnitt 6), mit Zahlen.
- Re-Identifikation über Kontext (seltene Kombinationen von Details).

OpenAnonymizer ist eine technische Schutzmaßnahme, keine Rechtsgrundlage und keine Zertifizierung.
