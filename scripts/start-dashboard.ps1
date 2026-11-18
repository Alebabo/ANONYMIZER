# Starts the dashboard as a production build on http://localhost:3000 and opens the browser.
# Rebuilds only when sources changed since the last build; if the server already runs, just opens it.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$port = 3000
$url = "http://localhost:$port"
Set-Location $root
$host.UI.RawUI.WindowTitle = "OpenAnonymizer Dashboard"

if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
  Start-Process $url
  exit
}

# With .env and Docker the API runs locally (docker compose) and the dashboard is live, so uploads and
# traces are real. Without them it falls back to demo mode with example data.
$health = "http://127.0.0.1:8080/health"
function Test-Api { try { Invoke-WebRequest $health -UseBasicParsing -TimeoutSec 2 | Out-Null; $true } catch { $false } }
if ((Test-Path ".env") -and (Get-Command docker -ErrorAction SilentlyContinue)) {
  if (-not (Test-Api)) {
    $desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    docker info *> $null
    if ($LASTEXITCODE -ne 0 -and (Test-Path $desktop)) {
      Write-Host "Starting Docker Desktop..."
      Start-Process $desktop
      for ($i = 0; $i -lt 90 -and $LASTEXITCODE -ne 0; $i++) { Start-Sleep 2; docker info *> $null }
    }
    Write-Host "Starting OpenAnonymizer API (first run builds the image, takes a few minutes)..."
    docker compose up -d --build
    for ($i = 0; $i -lt 120 -and -not (Test-Api); $i++) { Start-Sleep -Milliseconds 1000 }
  }
  if (Test-Api) { $env:ANONYMIZER_API_URL = "http://127.0.0.1:8080" } else { Write-Host "API not reachable, dashboard runs in demo mode." }
}

if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }

$buildId = Join-Path $root ".next\BUILD_ID"
$sources = "app", "components", "lib", "middleware.ts", "next.config.ts", "package.json"
$built = if (Test-Path $buildId) { (Get-Item $buildId).LastWriteTime } else { [datetime]::MinValue }
$changed = Get-ChildItem $sources -Recurse -File -ErrorAction SilentlyContinue | Where-Object LastWriteTime -gt $built | Select-Object -First 1
if ($changed) {
  Write-Host "Building (sources changed)..."
  npm run build
  if ($LASTEXITCODE -ne 0) { Read-Host "Build failed, press Enter to close"; exit 1 }
}

# Open the browser as soon as the server answers.
Start-Job -ArgumentList $url {
  param($url)
  for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process $url; return } catch { Start-Sleep -Milliseconds 500 }
  }
} | Out-Null

Write-Host "OpenAnonymizer dashboard on $url - close this window to stop it."
# Localhost only: the dashboard is not meant to be reachable from the network.
npx next start -H 127.0.0.1 -p $port
