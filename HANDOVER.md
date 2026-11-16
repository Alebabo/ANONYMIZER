# Übergabe: Cato als Datenschutz-Proxy für Kundenchats und Prompts

Stand: 15.11.2026. Diese Datei ist die Arbeitsanleitung, um Cato auf der Arbeit zu testen, an die eigene Umgebung anzupassen und später vor Produktion zu betreiben. Hintergrund und Designentscheidungen stehen in [plan.md](plan.md), die technische Referenz in [docs/conversations.md](docs/conversations.md), [docs/prompts.md](docs/prompts.md) und [docs/mcp.md](docs/mcp.md).

---

## 1. Kurzfassung

**Problem:** Claude darf bei der Arbeit nur an `sbx`/`develop`, nicht an `prod`, weil dort Kundendaten liegen. Für Prompt-Arbeit braucht man aber echte Chats.

**Lösung:** Cato läuft **im Firmennetz neben Prod** und ist das Einzige, womit Claude spricht. Claude bekommt:

- **Kundenchats**, aber nur geschützt: `PERSON_001`, `EMAIL_001` und `ORDER_NUMBER_001` statt echter Werte, `[REDACTED]` statt IBAN. Nachrichten mit Gesundheitsdaten kommen gar nicht (`content: null`).
- **Statistiken**, z. B. Konversationen pro Prompt-Version. Kleine Gruppen werden unterdrückt.
- **Prompts** lesen, vergleichen und als **Entwurf** anlegen. Auf `production` setzen kann nur ein Mensch im Dashboard.

```
Claude Code / Cursor (Laptop, kein Prod-Zugriff)
        │  MCP über HTTPS + persönlicher Cato-Key      ← nur Platzhalter-Daten
        ▼
Cato (Firmennetz, neben Prod)
   ├─ Quelle lesen (read-only): Langfuse | eigene Chat-DB über 2 HTTP-Endpunkte | JSONL-Export
   ├─ Erkennen → Klassifizieren → Policy → Pseudonymisieren (pro Nachricht)
   ├─ Prompt-Store (lokal oder Langfuse), Entwürfe geprüft
   └─ Traces + Audit-Log (wer hat was gelesen, nie Inhalte)
```

**Stand:**

- Implementiert und getestet: 292 Tests, End-to-End mit echtem MCP-Client, Dashboard im Live-Modus.
- Nur mit **synthetischen** Daten getestet. Die Trefferquote auf euren echten Chats ist **unbekannt**.

---

## 2. Vor dem ersten Prod-Kontakt (nicht überspringen)

| # | Punkt | Warum | Erledigt |
|---|---|---|---|
| 1 | **Freigabe von Security / Datenschutz** einholen | Ohne Freigabe ist ein selbstgebauter Proxy Schatten-IT mit Kundendaten, auch wenn er gut ist. Gesprächsleitfaden: Abschnitt 13 | ☐ |
| 2 | **Vertrag mit Anthropic** klären (DPA, ggf. Zero Data Retention) | Auch pseudonymisierte Daten verlassen das Haus | ☐ |
| 3 | **Evaluation auf echter Stichprobe** (Abschnitt 7) | Erst messen, dann anschließen | ☐ |
| 4 | **Arbeitsvertrag / IP** klären | Wer besitzt Anpassungen, die in der Arbeitszeit entstehen? Firmenspezifisches gehört nach `local/` oder in ein Firmen-Repo (Abschnitt 11) | ☐ |
| 5 | **Pro Person ein eigener API-Key** | Tageslimit und Audit-Log hängen am Key | ☐ |

Bis dahin: nur mit Beispieldaten und `sbx`/`develop` arbeiten. Das ist mit dieser Anleitung vollständig möglich.

---

## 3. Phase A: Lokal mit Beispieldaten (Laptop, ca. 20 Minuten)

Ziel: sehen, dass alles läuft, bevor irgendeine Firmenquelle angeschlossen wird.

### 3.1 Installation

Voraussetzungen: Python ≥ 3.11, Git, ca. 2 GB Platz für die Sprachmodelle. Unter Windows: WSL oder Docker (Abschnitt 6).

```bash
git clone https://github.com/Alebabo/Cato.git && cd Cato
```

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -e "packages/core[dev]" -e sdk/python
```

```bash
python -m spacy download de_core_news_lg && python -m spacy download en_core_web_lg
```

Hinter einem Firmen-Proxy: `pip` und der spaCy-Download brauchen `HTTPS_PROXY` und ggf. `REQUESTS_CA_BUNDLE`/`PIP_CERT` mit dem Firmen-CA-Zertifikat.

Kontrolle:

```bash
cd packages/core && python -m pytest -q && cd ../..
```

Erwartet: `292 passed, 1 skipped`. Der Skip kommt von einem Gateway-Test, der das Paket `openai` braucht.

### 3.2 Server mit Beispieldaten starten

```bash
export CATO_API_KEYS=cato_demo_key_change_me_0123456789
export CATO_ADMIN_KEYS=cato_demo_admin_change_me_0123456789
export CATO_BOOTSTRAP_ADMIN_EMAIL=ich@example.org CATO_BOOTSTRAP_ADMIN_PASSWORD=bitte-aendern-123
export CATO_SOURCE=jsonl CATO_SOURCE_PATH=examples/support/conversations.jsonl
export CATO_CUSTOM_PATTERNS=examples/support/patterns.yaml
export CATO_PROMPTS=local CATO_MCP_HTTP=1
cato-api
```

In jedem weiteren Terminal für die Befehle unten (Client-Seite, ein Key je Variable):

```bash
export CATO_API_KEY=cato_demo_key_change_me_0123456789 CATO_ADMIN_KEY=cato_demo_admin_change_me_0123456789
```

Läuft auf `http://127.0.0.1:8080`. Die Daten (Vault, Policies, Audit usw.) liegen in `./data/`.

### 3.3 Claude Code anbinden

```bash
claude mcp add --transport http cato http://127.0.0.1:8080/mcp --header "Authorization: Bearer cato_demo_key_change_me_0123456789"
```

```bash
claude mcp list
```

Testfragen an Claude:

- „Liste die letzten 10 Support-Konversationen mit Tags auf.“
- „Lies drei Konversationen zum Thema retoure und fasse die häufigsten Probleme zusammen.“
- „Vergleiche support-bot@11 und @12 anhand der Statistik nach Prompt-Version.“
- „Lege einen neuen Entwurf für den Prompt support-bot an, der zuerst nach der Bestellnummer fragt.“

Was du sehen solltest:

- Namen erscheinen als `PERSON_001`, Bestellnummern als `ORDER_NUMBER_001`.
- Eine Nachricht mit „Diabetes“ hat `content: null`.
- Einen Entwurf mit einem echten Namen lehnt Cato ab.

### 3.4 Dashboard (optional, aber für das Promoten nötig)

Node.js ≥ 22:

```bash
npm ci && CATO_API_URL=http://127.0.0.1:8080 npm run dev
```

Öffne `http://localhost:3000` und melde dich mit der Bootstrap-E-Mail und dem Passwort an.

- **Conversations:** Liste, Statistik nach Prompt-Version, eine Konversation öffnen (zählt gegen dein Tageslimit).
- **Prompts → support-bot:** Diff zur Vorversion, Label setzen.
- **Audit Logs:** jeder Lesezugriff und jede Label-Änderung.

### 3.5 Leck-Check ausprobieren

```bash
cato leak-check --api http://127.0.0.1:8080 --key cato_demo_key_change_me_0123456789 --limit 24
```

Erwartet: `"findings": 0`. Zum Vergleich den Server ohne `CATO_CUSTOM_PATTERNS` starten und erneut prüfen. Dann erscheinen 15 Funde (`long_number`), weil Bestell-, Kunden- und Ticketnummern ohne Patterns nicht erkannt werden. Genau so findest du später eure Lücken.

---

## 4. Phase B: Gegen sbx / develop

Hier wird zum ersten Mal eine Firmenquelle angeschlossen, aber eine, an die Claude ohnehin darf. Cato kann dafür noch auf dem Laptop laufen.

### 4.1 Welche Quelle?

| Wo liegen die Chats? | `CATO_SOURCE` | Aufwand |
|---|---|---|
| In **Langfuse** als Sessions/Traces | `langfuse` | Nur Keys eintragen (4.2) |
| In einer **eigenen DB** / einem Backend-Service | `http` | Zwei read-only Endpunkte bauen (4.3), ca. ½–1 Tag |
| Nur als **Export** möglich | `jsonl` | Export ins Format aus `docs/conversations.md` bringen |

### 4.2 Langfuse

Die Keys findest du in Langfuse unter Project Settings → API Keys, für das **sbx-Projekt**.

```bash
export CATO_SOURCE=langfuse
export CATO_SOURCE_URL=https://langfuse-sbx.firma.intern
export CATO_SOURCE_PUBLIC_KEY=pk-lf-...
export CATO_SOURCE_SECRET_KEY=sk-lf-...
export CATO_PROMPTS=langfuse          # nutzt dieselben Langfuse-Keys, wenn CATO_SOURCE=langfuse
unset CATO_SOURCE_PATH
```

Verbindung prüfen. Das gibt nur Zahlen aus, keine Inhalte:

```bash
cato source-check --protect
```

Worauf du achten musst:

- **Mapping:** Jede Langfuse-Session wird eine Konversation. Jeder Trace wird zu `input` → user und `output` → assistant. Wenn eure App im Trace-Input den **ganzen Verlauf** loggt, nimmt Cato die **letzte** User-Nachricht.
- **Format prüfen:** Schau dir mit `get_conversation` 2–3 Konversationen an. Stimmen Reihenfolge und Rollen nicht, ist die Funktion `_text()` in `packages/core/src/cato/sources/__init__.py` die Stelle zum Anpassen.
- **Statistik nach Prompt-Version:** Cato liest `prompt_name` (oder `prompt`) und `prompt_version` aus den **Trace-Metadaten**. Setzt eure App das nicht, fehlt die Zuordnung. Zusätzlich liefert die Session-Liste von Langfuse keine Prompts mit. `conversation_stats(group_by="prompt_version")` funktioniert mit Langfuse deshalb nur eingeschränkt. Die Alternative ist ein eigener HTTP-Endpunkt (4.3).
- **Prompts in Langfuse:** Cato legt Versionen **ohne Label** an. `production` setzt ein Admin im Cato-Dashboard; Cato ruft dafür die Langfuse-API auf. Ordner-Namen mit `/` werden nicht unterstützt.

### 4.3 Eigene Chat-DB (HTTP-Vertrag)

Ihr baut neben der Chat-DB zwei GET-Endpunkte mit einem **read-only DB-User**. Vertrag und FastAPI-Beispiel: [docs/conversations.md → HTTP contract](docs/conversations.md#http-contract).

```bash
export CATO_SOURCE=http
export CATO_SOURCE_URL=https://chat-export-sbx.firma.intern/api
export CATO_SOURCE_KEY=...            # Bearer-Key, den euer Endpunkt prüft
# oder HTTP Basic (z. B. technischer Nutzer), nicht beides:
# export CATO_SOURCE_USER=cato CATO_SOURCE_PASSWORD=...
```

Tipps:

- Felder `prompt` und `prompt_version` mitliefern, dann funktioniert die Statistik pro Prompt-Version voll.
- `tags` (Kategorie, Intent, Ergebnis) mitliefern, das macht die Auswertung viel nützlicher.
- `next_cursor` darf eure interne ID sein. Cato gibt ihn nie nach außen.
- Neueste Konversationen zuerst.
- Multi-Agent-Bots: pro Nachricht `agent`, `action` und `subtopic` mitliefern. Nur Enum-Werte, nie Freitext.
- Bezeichner wie `TRANSACTION` oder `CARD_LOCK_EMB` hält die Erkennung oft für Organisationen und verwirft sie. Die festen Namen in eine Datei unter `local/` schreiben, eine pro Zeile, exakt so wie im Tag (`agent:TRANSACTION`) bzw. im Feld (`TRANSACTION`), und `CATO_CONVERSATIONS_LABELS` darauf setzen. `cato source-check --protect` zeigt unter `labels`, wie viele noch wegfallen.

### 4.4 Eigene Muster (Bestellnummern usw.)

Kopiere `examples/support/patterns.yaml` nach `local/patterns.yaml` (der Ordner `local/` ist gitignoriert) und passe die Regexe an eure Formate an. Beispiele:

```yaml
patterns:
  - name: order_number
    pattern: '\b[A-Z]{2}-\d{8}\b'        # z. B. DE-12345678
    confidence: 0.95
  - name: customer_number
    pattern: '\bK\d{7}\b'
    context_words: ['kunden', 'kd']
    confidence: 0.9
  - name: contract_number
    pattern: '\bV-\d{4}-\d{6}\b'
    confidence: 0.95
```

```bash
export CATO_CUSTOM_PATTERNS=local/patterns.yaml
```

- Die Namen `customer_number`, `order_number`, `ticket_number`, `contract_number`, `invoice_number` und `tracking_number` werden von `support-default` **pseudonymisiert**: Gleiche Nummer ergibt gleichen Platzhalter, damit die Analyse funktioniert.
- Jeder andere Name wird **geschwärzt**, oder du ergänzt eine Regel in deiner Policy (5.2).
- Eine ungültige Datei verhindert den Start. Das ist Absicht.

---

## 5. Anpassen

### 5.1 Was ist wo?

| Thema | Datei | Typische Anpassung |
|---|---|---|
| Langfuse-Mapping | `packages/core/src/cato/sources/__init__.py` → `_text()`, `LangfuseSource.get()` | Wo im Trace-Input steht die User-Nachricht? Welche Metadaten-Keys für den Prompt? |
| Neue Quelle | `packages/core/src/cato/sources/__init__.py` | Klasse mit `list()`, `get()`, `describe()`, in `source_from_env()` registrieren |
| Erkennung eurer Nummern | `local/patterns.yaml` (`CATO_CUSTOM_PATTERNS`) | Regex pro Format |
| Namen in Chats | `packages/core/src/cato/detect/recognizers.py` → `SelfIntroductionRecognizer` | Weitere Einleitungen („Hier schreibt …“) |
| Falsch erkannte Wörter | `packages/core/src/cato/detect/engine.py` → `NER_STOPWORDS` | Wörter, die NER fälschlich als Namen markiert (z. B. euer Produktname) |
| Was wird wie behandelt | eigene Policy (5.2) | z. B. Gesundheitsdaten schwärzen statt Nachricht zurückhalten |
| Limits | Umgebungsvariablen (Abschnitt 9) | Tageslimit, k, Seitengrößen |
| Prüfung von Prompt-Entwürfen | `packages/core/src/cato/prompts.py` → `BENIGN_TYPES`, `_findings()` | Welche Typen in Prompts erlaubt sind |
| Anweisungen an Claude | `packages/core/src/cato/mcp/server.py` → `INSTRUCTIONS`, Tool-Beschreibungen | Hausregeln, Tonalität |
| Dashboard | `app/(app)/conversations/`, `app/(app)/prompts/`, `lib/cato-api.ts` | Spalten, Ansichten |

Nach jeder Code-Änderung laufen lassen:

```bash
cd packages/core && python -m pytest -q
```

### 5.2 Eigene Policy

Nicht die eingebaute Datei ändern, sondern eine eigene Version hochladen. Die Befehle erwarten `CATO_API_KEY` (dein Key) und `CATO_ADMIN_KEY` (Admin-Key) als Umgebungsvariablen (siehe 3.2).

1. Kopiere `packages/core/src/cato/policy/builtin/support-default.yaml` nach `local/support-firma.yaml` und setze `name: support-firma`.
2. Vorher gegen die aktive Policy testen (Dry-Run, nichts wird gespeichert):

```bash
python - <<'PY'
import json, os, urllib.request
yaml = open("local/support-firma.yaml").read()
body = {"text": "Ich habe Diabetes, Bestellung DE-12345678", "candidate_yaml": yaml, "against": "support-default"}
req = urllib.request.Request("http://127.0.0.1:8080/v1/policies/dry-run", json.dumps(body).encode(),
                             {"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["CATO_API_KEY"]})
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
PY
```

3. Hochladen (Admin-Key) und aktivieren:

```bash
python -c "import json; print(json.dumps({'yaml': open('local/support-firma.yaml').read()}))" | curl -s -X POST localhost:8080/v1/policies -H "X-API-Key: $CATO_ADMIN_KEY" -H 'Content-Type: application/json' -d @-
```

```bash
export CATO_CONVERSATIONS_POLICY=support-firma     # Server neu starten; unbekannter Name = Startfehler
```

Häufige Änderung: Gesundheitsdaten nur **schwärzen** statt die ganze Nachricht zurückzuhalten. In der Regel `special_categories_external` die `action: local_only` durch `action: redact` ersetzen. Das erst tun, wenn die Evaluation zeigt, dass die Begriffe zuverlässig erkannt werden; die Erkennung arbeitet mit Wortlisten und übersieht Synonyme.

### 5.3 API-Keys pro Person

Mit dem Admin-Key, ohne Dashboard:

```bash
curl -s -X POST localhost:8080/v1/api-keys -H "X-API-Key: $CATO_ADMIN_KEY" -H 'Content-Type: application/json' -d '{"name":"alex-claude-code","role":"user"}'
```

Der Key wird **einmal** angezeigt und nur als Hash gespeichert. Alternativ geht es im Dashboard unter API Keys. Dashboard-Nutzer legst du mit `cato user create` an oder im Dashboard unter Settings → Members.

---

## 6. Phase D: Betrieb neben Prod

Erst nach Abschnitt 2 und Phase C (Abschnitt 7).

### 6.1 Docker Compose

```bash
cp .env.example .env
```

In `.env` setzen:

- Bootstrap-Admin, `CATO_ADMIN_KEYS`, `CATO_VAULT_KEY`.
- Quelle (`CATO_SOURCE_*`), `CATO_PROMPTS`, `CATO_MCP_HTTP=1`, `CATO_CUSTOM_PATTERNS=/config/patterns.yaml`.

Erzeugen kannst du die Werte mit:

```bash
python -c "import secrets; print('cato_' + secrets.token_urlsafe(32))"
```

```bash
python -c "from cato.vault import VaultKey; print(VaultKey.generate().to_b64())"
```

In `docker-compose.yml` das Verzeichnis mit Patterns und Policy einhängen:

```yaml
    volumes:
      - cato-data:/data
      - ./local:/config:ro
```

```bash
docker compose up -d --build
```

```bash
docker compose exec api cato source-check --protect
```

Beim Build hinter einem Firmen-Proxy braucht der Build das CA-Zertifikat: `docker build --secret id=ca_bundle,src=firmen-ca.crt ...` (siehe `docs/API.md`). Das Image ist mehrere GB groß (Sprachmodelle).

### 6.2 Netzwerk

- Cato lauscht nur auf `127.0.0.1:8080`. Davor gehört ein **Reverse Proxy mit TLS** (nginx, Traefik, euer Ingress), z. B. `https://cato.firma.intern`.
- **Ausgehend** braucht Cato nur die Quelle (Langfuse bzw. euren Endpunkt), keinen Internetzugang.
- **Eingehend** nur aus dem Netz, in dem die Laptops sind (VPN). Nicht öffentlich.
- `CATO_MCP_ALLOWED_HOSTS=cato.firma.intern` aktiviert den Schutz gegen DNS-Rebinding.
- Lesezugriff auf die Quelle: read-only User, wenn möglich auf einer **Replica**.

### 6.3 Claude Code auf die Prod-Instanz

```bash
claude mcp add --transport http cato https://cato.firma.intern/mcp --header "Authorization: Bearer <persönlicher Key>"
```

Claude Desktop und Konnektoren auf claude.ai brauchen OAuth. Das ist noch nicht eingebaut (Abschnitt 12). Claude Code und Cursor funktionieren mit dem Header.

### 6.4 Backups

- **`CATO_VAULT_KEY` außerhalb des Servers sichern.** Ohne ihn ist der Vault (die Zuordnung Platzhalter → echter Wert) nicht mehr lesbar.
- Das Volume `cato-data` sichern: Vault, Policies, Audit-Log, Prompts (lokal), ID-Zuordnung.

---

## 7. Phase C: Evaluation auf echter Stichprobe

Das ist der wichtigste Schritt vor Prod. Er darf **nur von einer berechtigten Person im geschützten Bereich** gemacht werden, ohne Cloud-LLM. Ergebnisse und Stichproben bleiben in `local/` bzw. auf dem geschützten System.

### 7.1 Schnelltest: Leck-Check

1. Cato im geschützten Bereich gegen die Prod-Quelle starten (Docker, Abschnitt 6.1). Noch **kein** Laptop wird angebunden.
2. Optional eine Liste bekannter echter Werte aus der Stichprobe exportieren: Kundennamen, E-Mails, Kunden- und Bestellnummern aus dem CRM. Eine Zeile pro Wert, nach `local/stichprobe.secrets.txt` (gitignoriert).
3. Leck-Check:

```bash
cato leak-check --api http://127.0.0.1:8080 --key $CATO_API_KEY --limit 200 --secrets local/stichprobe.secrets.txt --details
```

Ausgabe:

- Pro Fund: opake Konversations-ID, Nachrichtennummer, Art und ein **maskiertes** Beispiel (`DE********* (12 chars)`).
- Bekannte Werte erscheinen nur als Zeilennummer der Secrets-Datei.
- Exit-Code 1, wenn etwas gefunden wurde.

| Fund-Art | Bedeutung | Maßnahme |
|---|---|---|
| `long_number` | Lange Ziffernfolge im Output: meist eine eurer Nummern ohne Pattern | Pattern ergänzen (4.4) |
| `email`, `iban`, `phone` | Sollte nie vorkommen | Fall ansehen (Admin, im geschützten Bereich), Issue anlegen |
| `known_value` | Ein bekannter echter Wert ist durchgerutscht, meist ein Name ohne Kontext | Einleitung im `SelfIntroductionRecognizer` ergänzen oder Policy verschärfen |
| `url_with_params` | Links mit Parametern (Tracking, Tokens) | Ggf. Pattern für eure Domains |

Die Prüfung liest über die normale API und zählt gegen das Tageslimit des Keys. Für 200 Konversationen einen eigenen Key mit erhöhtem Limit verwenden (`CATO_CONVERSATIONS_DAILY_LIMIT`).

Einschränkung: Der Leck-Check findet nur, was als Muster oder bekannter Wert vorliegt. Namen ohne Liste findet er nicht. Dafür ist 7.2 da.

### 7.2 Gründlich: Korpus mit Recall-Messung

1. 30–50 typische Chats auswählen, darunter bewusst schwierige: kleingeschrieben, Tippfehler, Adressen, Nummern.
2. Pro Chat eine YAML-Datei in `local/korpus/` anlegen. Format wie `packages/core/tests/corpus/de_support.yaml`:

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
CATO_CUSTOM_PATTERNS=local/patterns.yaml cato eval local/korpus
```

4. Zahlen festhalten: `recall` (Anteil gefundener Werte) und `missed` (was durchgerutscht ist). Patterns und Regeln nachziehen, wiederholen.
5. Das Ergebnis (Recall, Restrisiko, getroffene Maßnahmen) dem Datenschutz vorlegen. Die Entscheidung, ob das reicht, trifft nicht ihr allein.

### 7.3 Bekanntes Verhalten auf Chat-Texten

- **Gut erkannt:** E-Mail, Telefon, IBAN, Adressen, Anrede plus Name („Frau Schmidt“), Selbstvorstellungen („mein name ist anna müller“, auch kleingeschrieben), eure Nummern mit Patterns.
- **Schwach:** **nackte Namen ohne Kontext**, kleingeschrieben („danke anna“). Die hängen an der statistischen Namenserkennung (NER) und sind das größte Restrisiko.
- **Zu viel geschwärzt:** NER markiert in kleingeschriebenem Text normale Wörter als Namen („ich komme nicht mehr in mein konto“ ergibt zwei `PERSON_`-Platzhalter). Kostet Lesbarkeit, nicht Datenschutz. Gegenmittel: `NER_STOPWORDS`.

---

## 8. Arbeiten mit Claude: Beispiele

Mit Cato als MCP-Server in Claude Code:

- „Zeig mir die Statistik der letzten 7 Tage nach Tag. Welche Themen dominieren?“
- „Lies 10 Konversationen mit Tag `retoure` und sag mir, wo der Bot schlecht antwortet. Zitiere die Stellen.“
- „Hol den Prompt support-bot mit Label production und schlag eine Änderung vor, die die Rückfragen bei Retouren reduziert. Lege sie als Entwurf an.“
- „Vergleiche Version 12 und 13 von support-bot und erklär die Unterschiede.“
- „Wie viele Konversationen hatte support-bot@12 im Vergleich zu @11, und wie lang waren sie im Schnitt?“

Regeln, die Claude über die Server-Anweisungen kennt, die du aber auch kennen solltest:

- Jeder `get_conversation` zählt gegen **dein** Tageslimit (Standard 200) und steht im Audit-Log.
- `content: null` heißt: von der Policy zurückgehalten. Claude soll das nicht rekonstruieren.
- Kunden können in Chats Text schreiben, der wie eine Anweisung aussieht (Prompt Injection). Deshalb kann Claude nur **Entwürfe** anlegen; Labels setzt ein Mensch.
- Platzhalter (`PERSON_001`) gelten nur innerhalb **einer** Konversation. `PERSON_001` in zwei Chats sind verschiedene Personen.

---

## 9. Konfiguration (alle relevanten Variablen)

| Variable | Default | Empfehlung |
|---|---|---|
| `CATO_SOURCE` | – | `langfuse`, `http` oder `jsonl` |
| `CATO_SOURCE_PATH` | – | jsonl: Pfad zur Datei |
| `CATO_SOURCE_URL` | – | http: Basis-URL des Vertrags; langfuse: Host |
| `CATO_SOURCE_KEY` | – | http: Bearer-Key |
| `CATO_SOURCE_PUBLIC_KEY` / `_SECRET_KEY` | – | langfuse |
| `CATO_SOURCE_TIMEOUT` | 30 | Sekunden |
| `CATO_CONVERSATIONS_POLICY` | `support-default` | eigene Policy nach 5.2 |
| `CATO_CONVERSATIONS_DAILY_LIMIT` | 200 | pro Key und UTC-Tag; streng anfangen |
| `CATO_CONVERSATIONS_MIN_GROUP` | 10 | k für Statistiken |
| `CATO_CONVERSATIONS_STATS_SCAN` | 5000 | max. gelesene Listeneinträge pro Statistik |
| `CATO_CONVERSATIONS_MAX_MESSAGES` | 500 | pro Konversation |
| `CATO_CONVERSATIONS_DB` | `data/conversations.db` | Zuordnung der opaken IDs und Tageszähler |
| `CATO_CUSTOM_PATTERNS` | – | `local/patterns.yaml` |
| `CATO_PROMPTS` | – | `local` oder `langfuse` |
| `CATO_PROMPTS_DB` | `data/prompts.db` | local |
| `CATO_PROMPTS_URL` / `_PUBLIC_KEY` / `_SECRET_KEY` | – | Langfuse, falls nicht dieselbe Instanz wie die Quelle |
| `CATO_MCP_HTTP` | 0 | `1` = MCP unter `/mcp` |
| `CATO_MCP_ALLOWED_HOSTS` | – | eure Cato-Domain |
| `CATO_VAULT_KEY` | – | **in Prod setzen**: stabile Platzhalter, Admin kann zurückübersetzen |
| `CATO_API_KEYS` / `CATO_ADMIN_KEYS` | – | Admin-Key nur für Policy und Labels; Personen-Keys über die API (5.3) |

Vollständige Liste: `.env.example` und `packages/core/src/cato/api/settings.py`.

---

## 10. Fehlersuche

| Symptom | Ursache | Lösung |
|---|---|---|
| `401` auf `/mcp` | Key fehlt oder ist falsch | `claude mcp add ... --header "Authorization: Bearer <key>"` prüfen; `X-API-Key` geht auch |
| Claude sieht keine Conversation-Tools | `CATO_SOURCE` nicht gesetzt oder `CATO_MCP_HTTP` fehlt | `curl -H "Authorization: Bearer <key>" localhost:8080/v1/sources` |
| `404 conversation access is not configured` | `CATO_SOURCE` fehlt | setzen, neu starten |
| `404 conversation not found; list conversations first` | ID unbekannt (anderer Key/Org oder DB gelöscht) | erst `list_conversations` |
| `429 daily limit … reached` | Tageslimit erreicht | Reset 00:00 UTC; ggf. Limit erhöhen |
| `400 tag filter not allowed` | Tag-Filter enthält Personendaten | Absicht (kein Orakel); nur Kategorien filtern |
| `502 Langfuse returned HTTP 401` | Falsche Langfuse-Keys / falsches Projekt | Keys aus dem richtigen Projekt |
| Start bricht ab mit Policy-Fehler | `CATO_CONVERSATIONS_POLICY` existiert nicht | Policy hochladen (5.2) oder Name korrigieren |
| Start bricht ab mit Pattern-Fehler | Ungültiges YAML oder Regex in `CATO_CUSTOM_PATTERNS` | Meldung nennt das Pattern |
| Prompt-Entwurf abgelehnt, obwohl harmlos | Voller Name oder Kontaktdaten im Text | Template-Variablen nutzen (`{{customer_name}}`) |
| Prompt gespeichert, aber mit `warnings` | Einzelwort von NER als Name erkannt („Lisa“, „Nenne“) | Vor dem Promoten ansehen, meist harmlos |
| `prompt_version`-Statistik leer | Quelle liefert keinen Prompt (Langfuse-Session-Liste) | App setzt Trace-Metadaten; besser HTTP-Vertrag |
| `NER disabled` in Warnungen | spaCy-Modelle fehlen | `python -m spacy download de_core_news_lg en_core_web_lg` |
| Dashboard zeigt „Example data“ | `CATO_API_URL` nicht gesetzt | `CATO_API_URL=http://127.0.0.1:8080 npm run dev` |

Werkzeuge, die keine Inhalte ausgeben:

- `cato source-check [--protect]`: Verbindung und Format der Quelle.
- `cato leak-check`: Funde im geschützten Output (maskiert).
- `GET /v1/traces`: Entscheidungen pro Lesezugriff (nur Typen und Zahlen).
- Dashboard → Audit Logs.

---

## 11. Firmenspezifisches und Git

- **`local/`** ist gitignoriert: eigene Patterns, Policies, Korpus, Secrets-Listen, Notizen. Echte Kundendaten (Stichproben, Secrets-Dateien) gehören **nie** in ein Repo, auch nicht in ein privates.
- Generische Verbesserungen (bessere Erkennung, Bugfixes) können ins Cato-Repo. Firmenspezifische Adapter (z. B. euer HTTP-Endpunkt) gehören ins Firmen-Repo.
- Vorher Abschnitt 2, Punkt 4 (IP) klären.
- Entwicklungsablauf: Branch, `python -m pytest -q` in `packages/core`, für Dashboard-Änderungen `npx tsc --noEmit && npx next build`. Die CI (`.github/workflows/ci.yml`) macht dasselbe plus `cato eval tests/corpus`.

---

## 12. Bekannte Grenzen und nächste Schritte

| Thema | Stand | Nächster Schritt |
|---|---|---|
| Trefferquote auf echten Chats | unbekannt | Phase C (Abschnitt 7) |
| Nackte Namen ohne Kontext | hängt an NER, Restrisiko | Messen; ggf. Namensliste aus dem CRM als Muster (nur im geschützten Bereich) |
| OAuth für Remote-MCP | fehlt | nötig für Claude Desktop und Konnektoren auf claude.ai; das `mcp`-SDK bringt die Serverseite mit |
| Suche in Chats | bewusst nicht vorhanden | nur über einen vorab anonymisierten Index (eigenes Projekt) |
| k-Anonymität | schützt nur Statistiken; die Liste zeigt Metadaten pro Konversation | Wenn Metadaten selbst heikel sind: Tags in der Quelle reduzieren |
| Langfuse-Statistik pro Prompt-Version | eingeschränkt | Trace-Metadaten setzen oder HTTP-Vertrag |
| Speicher | SQLite | für mehrere Instanzen PostgreSQL (Roadmap) |
| Streaming im Gateway, TypeScript-SDK | offen | Roadmap in README |

---

## 13. Leitfaden für das Gespräch mit Security / Datenschutz

**Was verlässt das Haus?**

- Nur Nachrichten, die die Policy erlaubt, und das pseudonymisiert. Namen, Kontaktdaten und eure Nummern werden zu Platzhaltern. Zahlungs- und Ausweisdaten werden geschwärzt.
- Nachrichten mit besonderen Kategorien (Gesundheit u. a., Art. 9 DSGVO) werden komplett zurückgehalten.
- Keine Original-IDs. Datumsangaben nur tagesgenau.

**Welche Kontrollen gibt es?**

- Read-only-Zugriff auf die Quelle; Cato schreibt nie in die Chat-DB.
- Persönliche Keys mit Tageslimit; jeder Lesezugriff steht im manipulationssicheren Audit-Log.
- Die Rückübersetzung von Platzhaltern geht nur mit Admin-Key im Haus und wird ebenfalls protokolliert.
- Claude kann keine Prompts in Produktion bringen; das macht ein Mensch.
- Policies sind deterministisch, versioniert und vorab per Dry-Run testbar.
- Logs und Traces enthalten keine Inhalte.

**Was ist das Restrisiko?**

- Nicht erkannte Personendaten, vor allem nackte Namen. Gemessen durch Phase C, mit Zahlen.
- Re-Identifikation über Kontext (seltene Kombinationen von Details). Begrenzt durch Tageslimit und Datumsvergröberung, nicht ausgeschlossen.

**Was entscheidet ihr?**

- Ob die gemessene Trefferquote reicht.
- Welches Tageslimit gilt.
- Ob Gesundheitsdaten zurückgehalten oder nur geschwärzt werden.
- Ob der Vertrag mit Anthropic die Übermittlung pseudonymisierter Daten abdeckt.

Cato ist eine technische Schutzmaßnahme, keine Rechtsgrundlage und keine Zertifizierung.
