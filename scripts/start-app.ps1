# Starts OpenAnonymizer as a desktop app: API via docker compose, dashboard on http://localhost:3000,
# shown in its own Edge app window. Closing the window stops the dashboard server (the API container keeps running).
# Meant to be launched hidden from the desktop shortcut: powershell -WindowStyle Hidden -File scripts\start-app.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$port = 3000
$url = "http://localhost:$port"
$log = Join-Path $env:TEMP "openanonymizer-app.log"
Set-Location $root
Add-Type -AssemblyName System.Windows.Forms
# Portable Node under %USERPROFILE%\tools\node when npm is not on PATH (same fallback as dev-local.ps1).
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  $nodeDir = Get-ChildItem "$env:USERPROFILE\tools\node" -Directory -ErrorAction SilentlyContinue | Select-Object -Last 1
  if ($nodeDir) { $env:PATH = "$($nodeDir.FullName);$env:PATH" }
}
$api = $null

function Fail($msg) {
  [System.Windows.Forms.MessageBox]::Show("$msg`n`nLog: $log", "OpenAnonymizer", "OK", "Error") | Out-Null
  exit 1
}
# cmd keeps native stderr away from PowerShell 5.1, which turns it into a terminating error under "Stop".
function Test-Docker { cmd /c "docker info >nul 2>&1"; $LASTEXITCODE -eq 0 }
function Test-Url($u) { try { Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 2 | Out-Null; $true } catch { $false } }
# Port check for the dashboard: "/" redirects to localhost/login, which Invoke-WebRequest tries on ::1 and times out.
function Test-Dashboard {
  $c = New-Object System.Net.Sockets.TcpClient
  try { $c.ConnectAsync("127.0.0.1", $port).Wait(1000) -and $c.Connected } catch { $false } finally { $c.Close() }
}

$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { Fail "Microsoft Edge not found." }
# Own profile so the Edge process lives exactly as long as the app window.
$profileDir = Join-Path $env:LOCALAPPDATA "OpenAnonymizer\edge-profile"

function Open-Window {
  Start-Process $edge -ArgumentList "--app=$url", "--user-data-dir=`"$profileDir`"", "--no-first-run", "--window-size=1400,900" -PassThru
}

# Already running (second double-click): just open another window.
if (Test-Dashboard) { Open-Window | Out-Null; exit }

# Small splash so the first start (image build, Next build) does not look like nothing happened.
$splash = New-Object System.Windows.Forms.Form -Property @{
  Text = "OpenAnonymizer"; Width = 360; Height = 110; StartPosition = "CenterScreen"
  FormBorderStyle = "FixedDialog"; ControlBox = $false; TopMost = $true
}
$label = New-Object System.Windows.Forms.Label -Property @{ Dock = "Fill"; TextAlign = "MiddleCenter"; Text = "Starting..." }
$splash.Controls.Add($label)
$splash.Show()
function Status($text) { $label.Text = $text; [System.Windows.Forms.Application]::DoEvents(); Add-Content $log $text }

Set-Content $log "OpenAnonymizer start $(Get-Date)"
$health = "http://127.0.0.1:8080/health"
if ((Test-Path ".env") -and (Get-Command docker -ErrorAction SilentlyContinue)) {
  if (-not (Test-Url $health)) {
    $desktop = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Docker) -and (Test-Path $desktop)) {
      Status "Starting Docker Desktop..."
      Start-Process $desktop
      for ($i = 0; $i -lt 90 -and -not (Test-Docker); $i++) { Start-Sleep 2; [System.Windows.Forms.Application]::DoEvents() }
    }
    Status "Starting API (first run takes a few minutes)..."
    cmd /c "docker compose up -d --build >> `"$log`" 2>&1"
    for ($i = 0; $i -lt 120 -and -not (Test-Url $health); $i++) { Start-Sleep 1; [System.Windows.Forms.Application]::DoEvents() }
  }
  if (Test-Url $health) { $env:ANONYMIZER_API_URL = "http://127.0.0.1:8080" } else { Status "API not reachable, demo mode." }
} elseif ((Test-Path ".env") -and (Test-Path ".venv\Scripts\anonymizer-api.exe")) {
  # No Docker: run the API locally from .venv (like dev-local.ps1). It stops together with the dashboard.
  if (-not (Test-Url $health)) {
    Status "Starting local API..."
    Get-Content ".env" | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object {
      $k, $v = $_ -split '=', 2
      Set-Item "env:$($k.Trim())" $v.Trim().Trim('"')
    }
    $env:ANONYMIZER_PORT = "8080"
    New-Item -ItemType Directory -Force "logs" | Out-Null
    $api = Start-Process (Join-Path $root ".venv\Scripts\anonymizer-api.exe") -WorkingDirectory (Join-Path $root "packages\core") `
      -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root "logs\api-local.log") -RedirectStandardError (Join-Path $root "logs\api-local.err.log")
    for ($i = 0; $i -lt 120 -and -not (Test-Url $health); $i++) { Start-Sleep 1; [System.Windows.Forms.Application]::DoEvents() }
  }
  if (Test-Url $health) { $env:ANONYMIZER_API_URL = "http://127.0.0.1:8080" } else { Status "API not reachable, demo mode." }
}

if (-not (Test-Path "node_modules")) { Status "Installing dependencies..."; cmd /c "npm install --no-audit --no-fund >> `"$log`" 2>&1" }

$buildId = Join-Path $root ".next\BUILD_ID"
$sources = "app", "components", "lib", "middleware.ts", "next.config.ts", "package.json"
$built = if (Test-Path $buildId) { (Get-Item $buildId).LastWriteTime } else { [datetime]::MinValue }
$changed = Get-ChildItem $sources -Recurse -File -ErrorAction SilentlyContinue | Where-Object LastWriteTime -gt $built | Select-Object -First 1
if ($changed) {
  Status "Building dashboard..."
  cmd /c "npm run build >> `"$log`" 2>&1"
  if ($LASTEXITCODE -ne 0) { $splash.Close(); Fail "Dashboard build failed." }
}

Status "Starting dashboard..."
# Localhost only: the dashboard is not meant to be reachable from the network.
$server = Start-Process cmd -ArgumentList "/c npx next start -H 127.0.0.1 -p $port >> `"$log`" 2>&1" -WindowStyle Hidden -PassThru
for ($i = 0; $i -lt 120 -and -not (Test-Dashboard); $i++) { Start-Sleep -Milliseconds 500; [System.Windows.Forms.Application]::DoEvents() }
$splash.Close()
if (-not (Test-Dashboard)) {
  taskkill /PID $server.Id /T /F | Out-Null
  if ($api) { taskkill /PID $api.Id /T /F | Out-Null }
  Fail "Dashboard did not start."
}

Open-Window | Wait-Process
# Wait for any further windows opened by a second double-click (they share the profile, so they share msedge.exe).
while (Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object { $_.CommandLine -like "*$profileDir*" }) { Start-Sleep 2 }
taskkill /PID $server.Id /T /F | Out-Null
if ($api) { taskkill /PID $api.Id /T /F | Out-Null }
