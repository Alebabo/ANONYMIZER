# Runs API (8080) and dashboard (3000) locally from this repo. Both stop when this window closes or on Ctrl+C.
# Usage: .\scripts\dev-local.ps1          start, stay in foreground, clean up on exit
#        .\scripts\dev-local.ps1 -Stop    kill whatever listens on the ports
param([switch]$Stop)
$root = Split-Path $PSScriptRoot -Parent
$ports = 8080, 3000

function Stop-Ports {
  foreach ($p in $ports) {
    Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
      taskkill /PID $_.OwningProcess /T /F 2>$null | Out-Null
    }
  }
}

Stop-Ports
if ($Stop) { Write-Host "Stopped."; exit }

# Load .env into this process so the child inherits it.
Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object {
  $k, $v = $_ -split '=', 2
  Set-Item "env:$($k.Trim())" $v.Trim().Trim('"')
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  $nodeDir = Get-ChildItem "$env:USERPROFILE\tools\node" -Directory -ErrorAction SilentlyContinue | Select-Object -Last 1
  if ($nodeDir) { $env:PATH = "$($nodeDir.FullName);$env:PATH" }
}
$env:ANONYMIZER_PORT = "8080"
$env:ANONYMIZER_API_URL = "http://127.0.0.1:8080"
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null

$api = Start-Process (Join-Path $root ".venv\Scripts\anonymizer-api.exe") -WorkingDirectory (Join-Path $root "packages\core") `
  -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root "logs\api-local.log") -RedirectStandardError (Join-Path $root "logs\api-local.err.log")
$dash = Start-Process cmd.exe -ArgumentList "/c npm run dev -- -H 127.0.0.1 -p 3000" -WorkingDirectory $root `
  -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root "logs\dashboard-local.log") -RedirectStandardError (Join-Path $root "logs\dashboard-local.err.log")

try {
  Write-Host "API http://127.0.0.1:8080 (pid $($api.Id)), dashboard http://127.0.0.1:3000 (pid $($dash.Id)). Close window or Ctrl+C to stop."
  while (-not $api.HasExited) { Start-Sleep 2 }
} finally {
  foreach ($p in $api, $dash) { if ($p) { taskkill /PID $p.Id /T /F 2>$null | Out-Null } }
  Stop-Ports
  Write-Host "Stopped."
}
