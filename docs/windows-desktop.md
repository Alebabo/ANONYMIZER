# Windows: Installation als Desktop-App

So wird OpenAnonymizer auf einem Windows-Laptop frisch installiert und per Doppelklick als App gestartet (eigenes Fenster, kein Konsolenfenster). Getestet auf Windows 11 mit Windows PowerShell 5.1.

## Voraussetzungen

- Git, Node.js (mit npm), Python 3.13 (mit pip)
- Docker Desktop (für die API mit spaCy-Modellen)
- Microsoft Edge (für das App-Fenster, ist bei Windows dabei)

## 1. Alte Installation entfernen (optional)

Vorher sichern, was nicht auf GitHub liegt:

- `.env` (Secrets, Bootstrap-Admin, API-Keys)
- `packages/core/data/` (lokale Daten, z.B. `playground.db`)
- lokale Branches, die nicht gepusht sind (`git branch -vv`, `git status`)

Dann den Ordner löschen:

```powershell
Remove-Item -Recurse -Force C:\Users\User\ANONYMIZER
```

Die Docker-Volumes (Accounts, Traces, Audit-Log unter `/data`) bleiben dabei erhalten. Bestehende Logins funktionieren nach der Neuinstallation weiter.

## 2. Repo klonen und `.env` zurücklegen

```powershell
git clone https://github.com/Alebabo/ANONYMIZER.git C:\Users\User\ANONYMIZER
Copy-Item <backup>\.env C:\Users\User\ANONYMIZER\.env
```

Ohne Backup: `.env.example` nach `.env` kopieren und ausfüllen. Ohne `.env` läuft das Dashboard nur im Demo-Modus.

## 3. Abhängigkeiten installieren

```powershell
cd C:\Users\User\ANONYMIZER
npm install

cd packages\core
python -m pip install -e ".[dev]"
python -m spacy download de_core_news_lg
python -m spacy download en_core_web_lg
```

Das Python-Paket und die spaCy-Modelle sind nur für Entwicklung und Tests (`pytest`, `anonymizer` CLI) nötig. Die App selbst nutzt die API im Docker-Container.

## 4. App-Verknüpfungen anlegen

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\User\ANONYMIZER\scripts\install-shortcuts.ps1
```

Das Script erstellt `OpenAnonymizer` auf dem Desktop und im Startmenü (kann an die Taskleiste angeheftet werden). Das Icon wird aus `public/brand/anonymizer-app-icon.svg` erzeugt und unter `%LOCALAPPDATA%\OpenAnonymizer\` abgelegt.

## 5. Starten

Doppelklick auf `OpenAnonymizer`. `scripts/start-app.ps1` macht dann:

1. Docker Desktop starten, falls es nicht läuft
2. API per `docker compose up -d --build` starten (beim ersten Mal wird das Image gebaut, dauert einige Minuten)
3. Dashboard bauen, falls sich Quellen geändert haben, und auf `http://localhost:3000` starten (nur localhost)
4. Dashboard in einem Edge-App-Fenster öffnen (eigenes Profil unter `%LOCALAPPDATA%\OpenAnonymizer\edge-profile`)

Ohne Docker startet das Script die API stattdessen lokal aus `.venv` (wie `scripts/dev-local.ps1`, Logs in `logs\api-local*.log`); sie stoppt zusammen mit dem Dashboard. Ist `npm` nicht im PATH, wird ein portables Node unter `%USERPROFILE%\tools\node` genutzt.

Ein kleines Fenster zeigt den Fortschritt. Wird das App-Fenster geschlossen, stoppt der Dashboard-Server. Die API (`127.0.0.1:8080`, inkl. MCP unter `/mcp`) läuft im Container weiter. Ein zweiter Doppelklick bei laufender App öffnet nur ein weiteres Fenster.

Log: `%TEMP%\openanonymizer-app.log`

Die Variante mit Konsolenfenster und normalem Browser-Tab gibt es weiterhin: `scripts/start-dashboard.ps1`.

## 6. Account anlegen

Neuer Nutzer (Passwort mindestens 12 Zeichen, wird abgefragt):

```powershell
docker compose exec api anonymizer user create --email ich@example.org --role admin
docker compose exec api anonymizer user list
```

Mehr dazu in [accounts.md](accounts.md).

Passwort vergessen: Die CLI hat keinen Reset. Wer Zugriff auf den Container hat, kann es direkt setzen (Passwort kommt über stdin, landet nicht in der Shell-History):

```powershell
'neues-passwort-123' | docker compose exec -T api python -c "import os,sys; from anonymizer.accounts import AccountStore, hash_password; a=AccountStore(os.environ.get('ANONYMIZER_ACCOUNTS_DB','data/accounts.db')); a._db.execute('UPDATE users SET password_hash=? WHERE email=?',(hash_password(sys.stdin.read().strip()),'ich@example.org')); a._db.commit()"
```

## Bekannte Stolperstellen

- **`start-dashboard.ps1` bricht ab, wenn Docker Desktop aus ist.** Windows PowerShell 5.1 macht aus der stderr-Ausgabe von `docker info` unter `$ErrorActionPreference = "Stop"` einen Abbruch. `start-app.ps1` ruft Docker deshalb über `cmd /c` auf.
- **`Invoke-WebRequest http://localhost:3000` hängt.** `/` leitet auf `http://localhost:3000/login` weiter, PowerShell 5.1 versucht das über IPv6 (`::1`), der Server hört aber nur auf `127.0.0.1`. `start-app.ps1` prüft das Dashboard deshalb per TCP-Port.
- **`npm audit` meldet Schwachstellen.** Nicht automatisch mit `--force` fixen, das kann Breaking Changes einspielen.
