# Deployment (Hetzner)

Produktivbetrieb von API und Dashboard auf einem Hetzner-Cloud-Server, automatisch ausgerollt aus `main`.

## Kurzfassung

- Adresse: `https://openanonymizer.tma-it-solution.de`
- Jeder Push auf `main` wird nach grüner CI automatisch deployt. Ist die CI rot, bleibt die laufende Version.
- Manuell: GitHub → Actions → **Deploy** → "Run workflow" (Branch `main`).
- Dauer: etwa 2–3 Minuten CI plus 1–3 Minuten Deploy.

## Architektur

```
Browser / API-Client / MCP-Client
        │ HTTPS (443)
        ▼
  Caddy (TLS, Let's Encrypt)            deploy/Caddyfile
   ├─ /v1/*, /health, /mcp  ──►  api:8080        packages/core (FastAPI, spaCy)
   └─ alles andere          ──►  dashboard:3000  Next.js standalone
                                   └─ spricht intern mit http://api:8080
```

| Komponente | Gebaut | Konfiguration |
|---|---|---|
| API | auf dem Server (`docker compose build`) | `docker-compose.yml`, `packages/core/Dockerfile`, `.env` |
| Dashboard | in GitHub Actions, per `docker load` übertragen | `deploy/dashboard.Dockerfile`, `next.config.ts` (`NEXT_OUTPUT=standalone`) |
| Caddy | offizielles Image `caddy:2.8-alpine` | `deploy/Caddyfile` |
| Server-Ergänzungen | – | `deploy/docker-compose.prod.yml` |

Das Dashboard wird nicht auf dem Server gebaut, weil `next build` mehr Arbeitsspeicher braucht als der Server hat.
Die lokale `docker-compose.yml` bleibt unverändert nutzbar; die Server-Teile liegen nur in `deploy/`.

## Ablauf eines Deploys

Workflow: `.github/workflows/deploy.yml`. Auslöser: Abschluss der CI auf `main` (nur bei Erfolg und nur für Pushes)
oder manueller Start.

1. **SSH einrichten**: privaten Schlüssel aus dem Secret laden (Kopierfehler wie fehlende Zeilenumbrüche werden
   repariert), Fingerprint ins Log schreiben, Host-Key des Servers per `ssh-keyscan` übernehmen.
2. **Server vorbereiten**: Docker installieren (falls fehlend), 2 GB Swap anlegen (falls keiner existiert), `rsync`
   installieren, Zielverzeichnis `/opt/anonymizer` anlegen.
3. **Code übertragen**: per `rsync --delete` nur `docker-compose.yml`, `packages/core/`, `examples/`, `deploy/`.
   `.env` wird nie überschrieben oder gelöscht.
4. **Dashboard-Image** in Actions bauen und per `docker save | ssh docker load` übertragen.
5. **`.env` anlegen**, nur beim allerersten Deploy: zufälliger API-Key, Admin-Key und Vault-Key.
6. **Ersten Admin eintragen**, nur wenn `ADMIN_EMAIL`/`ADMIN_PASSWORD` gesetzt sind und die `.env` noch keinen
   Eintrag hat.
7. **Starten**: `docker compose up -d --build --remove-orphans` mit
   `COMPOSE_FILE=docker-compose.yml:deploy/docker-compose.prod.yml`, danach alte Images aufräumen.
8. **Prüfen**: API über `http://127.0.0.1:8080/health`, Dashboard über Caddy mit `https://<domain>/login`.
   Schlägt einer der Checks fehl, ist der Lauf rot und die letzten Container-Logs stehen im Job-Log.

Läufe werden nacheinander abgearbeitet (`concurrency: deploy-production`), nie parallel.

## Konfiguration

### GitHub-Secrets (Settings → Secrets and variables → Actions → Repository secrets)

| Secret | Pflicht | Inhalt |
|---|---|---|
| `DEPLOY_SSH_KEY` | ja | privater Ed25519-Schlüssel; der öffentliche Teil liegt in `/root/.ssh/authorized_keys` |
| `DEPLOY_HOST` | nein | Server-IP oder Hostname; Standard `178.105.31.110` |
| `ADMIN_EMAIL` | nein | Login des ersten Dashboard-Admins |
| `ADMIN_PASSWORD` | nein | dessen Startpasswort; nach dem ersten Login ändern |

Optional als Repository-**Variablen**: `DEPLOY_USER` (Standard `root`), `DEPLOY_PATH` (Standard `/opt/anonymizer`).

### Server-`.env` (`/opt/anonymizer/.env`)

Liegt ausschließlich auf dem Server, nie im Repository. Wird beim ersten Deploy erzeugt und danach nicht mehr
angefasst. Alle Variablen: `.env.example`. Änderungen per SSH; wirksam beim nächsten Deploy oder mit
`docker compose up -d`.

**`ANONYMIZER_VAULT_KEY` außerhalb des Servers sichern** (Passwortmanager). Ohne ihn ist der Vault nicht mehr
lesbar und Pseudonymisierungen lassen sich nicht umkehren.

### Domain und TLS

- DNS bei IONOS: A-Record `openanonymizer` → `178.105.31.110` (optional AAAA auf die IPv6 des Servers).
- Caddy holt das Zertifikat beim ersten Aufruf automatisch und verlängert es selbst. Voraussetzung: Ports 80 und 443
  sind offen (keine Hetzner-Firewall bzw. Regeln dafür).
- Domain ändern: `deploy/Caddyfile` nutzt `ANONYMIZER_DOMAIN`; die Domain steht in `deploy/docker-compose.prod.yml`
  (Caddy, `ANONYMIZER_MCP_ALLOWED_HOSTS`, `ANONYMIZER_PUBLIC_API_URL`) und im Dashboard-Check des Workflows.

## Server neu aufsetzen

1. Bei Hetzner einen Server mit Ubuntu 24.04 anlegen und dabei den SSH-Key `github-deploy` auswählen.
   Hetzner trägt Keys **nur beim Erstellen** ein; ein später hinzugefügter Key wirkt nicht auf bestehende Server.
2. Neue IP als Secret `DEPLOY_HOST` setzen (oder Standard im Workflow ändern) und den DNS-Eintrag anpassen.
3. Deploy manuell starten. Docker, Swap, `.env` und Container werden automatisch eingerichtet.
4. Achtung: Eine neue `.env` bedeutet einen neuen Vault-Key. Zum Umzug mit Daten die alte `.env` und die
   Docker-Volumes (`anonymizer-data`, `caddy-data`) vom alten Server übernehmen.

## Deploy-Key tauschen

```bash
ssh-keygen -t ed25519 -f deploy_key -N "" -C github-deploy
```

1. Inhalt von `deploy_key.pub` auf dem Server an `/root/.ssh/authorized_keys` anhängen, den alten Eintrag entfernen.
2. Inhalt von `deploy_key` (inklusive BEGIN/END-Zeilen) als Secret `DEPLOY_SSH_KEY` setzen.
3. Lokale Datei `deploy_key` löschen. Der private Schlüssel gehört nie ins Repository.

Der Fingerprint des verwendeten Schlüssels steht im Log des Schritts "SSH einrichten".

## Betrieb

Per SSH auf dem Server, im Verzeichnis `/opt/anonymizer`:

```bash
export COMPOSE_FILE=docker-compose.yml:deploy/docker-compose.prod.yml
docker compose ps                       # Status
docker compose logs -f --tail 100 api   # Logs (api, dashboard, caddy)
docker compose restart api              # Neustart
free -h                                 # Speicher (1 GB RAM + Swap)
```

**Rollback**: den fehlerhaften Commit auf `main` per `git revert` zurücknehmen und pushen; der Deploy rollt den
vorherigen Stand aus. Alternativ in Actions einen älteren erfolgreichen Deploy-Lauf über "Re-run" erneut starten
(nutzt den Commit dieses Laufs).

**Daten**: Vault, Accounts, Audit-Log, Traces und Policies liegen im Docker-Volume `anonymizer-data`, Zertifikate in
`caddy-data`. Beide überstehen Deploys. Backups sind noch nicht eingerichtet (Hetzner-Backups oder Volume-Export).

## Fehlerbilder

| Meldung im Job-Log | Ursache | Lösung |
|---|---|---|
| `Secret DEPLOY_SSH_KEY fehlt` | Secret nicht angelegt, als Variable statt Secret, als Environment-Secret oder falscher Name | als **Repository secret** `DEPLOY_SSH_KEY` anlegen |
| `DEPLOY_SSH_KEY ist kein gültiger OpenSSH-Schlüssel` | unvollständig kopiert | Schlüssel erneut einfügen, möglichst am Laptop statt am Handy |
| `Permission denied (publickey,password)` bei korrektem Fingerprint | öffentlicher Schlüssel nicht auf dem Server | Key in `authorized_keys` eintragen oder Server mit ausgewähltem Key neu anlegen |
| `API-Health-Check fehlgeschlagen` | API startet nicht (Konfiguration, Speicher) | Logs im Job lesen; bei `Killed`/OOM mehr RAM |
| `Dashboard-Check fehlgeschlagen (HTTP 000)` | Caddy hat (noch) kein Zertifikat, DNS falsch, Ports zu | DNS-Eintrag prüfen, `docker compose logs caddy` |

## Bekannte Grenzen (Stand Vorab-Betrieb)

- 1 GB RAM: API mit spaCy-Modellen und Dashboard laufen nur mit Swap; Erkennung kann langsam sein. Für echten
  Betrieb mindestens 4 GB.
- Deploy als `root`; besser ein eigener User in der Gruppe `docker`.
- Der Host-Key des Servers wird bei jedem Lauf per `ssh-keyscan` übernommen statt fest hinterlegt.
- Beim Container-Austausch ist der Dienst einige Sekunden nicht erreichbar.
- Keine automatischen Backups.
