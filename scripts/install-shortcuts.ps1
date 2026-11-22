# Creates the OpenAnonymizer app shortcuts (desktop + start menu) for scripts\start-app.ps1, with an .ico
# rendered from public\brand\anonymizer-app-icon.svg via headless Edge. Safe to re-run; replaces old shortcuts.
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
$root = Split-Path $PSScriptRoot -Parent
$dir = Join-Path $env:LOCALAPPDATA "OpenAnonymizer"
$ico = Join-Path $dir "OpenAnonymizer.ico"
New-Item -ItemType Directory -Force $dir | Out-Null

$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge not found." }

# SVG -> 256px PNG
$svg = Get-Content (Join-Path $root "public\brand\anonymizer-app-icon.svg") -Raw
$html = Join-Path $dir "icon.html"
$png = Join-Path $dir "icon.png"
Set-Content $html "<html><body style='margin:0'>$($svg -replace '<svg ', '<svg width="256" height="256" ')</body></html>" -Encoding utf8
Remove-Item $png -ErrorAction SilentlyContinue
& $edge --headless=new --disable-gpu --hide-scrollbars --window-size=256,256 --screenshot="$png" "file:///$($html -replace '\\', '/')" | Out-Null
for ($i = 0; $i -lt 20 -and -not (Test-Path $png); $i++) { Start-Sleep -Milliseconds 500 }

# Headless Edge renders the corners white, so clip to the icon's rounded square (rx 34 of 150 -> 58 of 256).
$src = [System.Drawing.Bitmap]::FromFile($png)
$full = New-Object System.Drawing.Bitmap 256, 256
$g = [System.Drawing.Graphics]::FromImage($full)
$g.SmoothingMode = "AntiAlias"; $g.InterpolationMode = "HighQualityBicubic"
$r = 58; $path = New-Object System.Drawing.Drawing2D.GraphicsPath
$path.AddArc(0, 0, 2 * $r, 2 * $r, 180, 90); $path.AddArc(256 - 2 * $r, 0, 2 * $r, 2 * $r, 270, 90)
$path.AddArc(256 - 2 * $r, 256 - 2 * $r, 2 * $r, 2 * $r, 0, 90); $path.AddArc(0, 256 - 2 * $r, 2 * $r, 2 * $r, 90, 90)
$path.CloseFigure(); $g.SetClip($path); $g.DrawImage($src, 0, 0, 256, 256); $g.Dispose(); $src.Dispose()

# Multi-size ICO with PNG-encoded entries
$sizes = 256, 64, 48, 32, 16; $pngs = @()
foreach ($s in $sizes) {
  $b = New-Object System.Drawing.Bitmap $s, $s
  $gg = [System.Drawing.Graphics]::FromImage($b); $gg.InterpolationMode = "HighQualityBicubic"; $gg.DrawImage($full, 0, 0, $s, $s); $gg.Dispose()
  $ms = New-Object System.IO.MemoryStream; $b.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $pngs += , $ms.ToArray(); $b.Dispose()
}
$full.Dispose()
$out = New-Object System.IO.MemoryStream; $w = New-Object System.IO.BinaryWriter $out
$w.Write([UInt16]0); $w.Write([UInt16]1); $w.Write([UInt16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
  $s = $sizes[$i] % 256
  $w.Write([byte]$s); $w.Write([byte]$s); $w.Write([byte]0); $w.Write([byte]0); $w.Write([UInt16]1); $w.Write([UInt16]32)
  $w.Write([UInt32]$pngs[$i].Length); $w.Write([UInt32]$offset); $offset += $pngs[$i].Length
}
foreach ($p in $pngs) { $w.Write($p) }
[System.IO.File]::WriteAllBytes($ico, $out.ToArray())

$shell = New-Object -ComObject WScript.Shell
$links = (Join-Path ([Environment]::GetFolderPath("Desktop")) "OpenAnonymizer.lnk"),
         (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\OpenAnonymizer.lnk")
foreach ($lnk in $links) {
  Remove-Item $lnk -ErrorAction SilentlyContinue
  $s = $shell.CreateShortcut($lnk)
  $s.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $s.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\scripts\start-app.ps1`""
  $s.WorkingDirectory = $root; $s.IconLocation = "$ico,0"; $s.WindowStyle = 7; $s.Description = "OpenAnonymizer"
  $s.Save()
  Write-Host "Created $lnk"
}
