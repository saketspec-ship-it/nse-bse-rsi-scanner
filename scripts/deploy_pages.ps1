# Runs the scanner (unless -SkipScan) and publishes the generated site/ folder
# to the gh-pages branch as a single orphan commit (force-push, so no history
# bloat). This is the RELIABLE update path: Yahoo Finance works from your home
# IP, unlike GitHub's cloud runners.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\deploy_pages.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\deploy_pages.ps1 -SkipScan
#   powershell -ExecutionPolicy Bypass -File scripts\deploy_pages.ps1 -ScanArgs "--limit 800"

param(
    [switch]$SkipScan,
    [string]$ScanArgs = "--fundamentals-scope signal"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if (-not $SkipScan) {
    Write-Host "Running scan..." -ForegroundColor Cyan
    & $python -m rsi_scanner.scan $ScanArgs.Split(" ")
    if ($LASTEXITCODE -ne 0) { throw "Scan failed (exit $LASTEXITCODE)" }
}

$site = Join-Path $root "site"
if (-not (Test-Path (Join-Path $site "index.html"))) { throw "site/index.html not found - run a scan first." }

$remote = (git remote get-url origin 2>$null)
if (-not $remote) { throw "No 'origin' remote. Run scripts\setup_github.ps1 first." }

Write-Host "Publishing site/ to gh-pages on $remote ..." -ForegroundColor Cyan
Push-Location $site
try {
    if (Test-Path ".git") { Remove-Item -Recurse -Force ".git" }
    git init -q
    git checkout -q -b gh-pages
    # .nojekyll so GitHub Pages serves files as-is.
    New-Item -ItemType File -Path ".nojekyll" -Force | Out-Null
    git add -A
    git -c user.name="rsi-scanner" -c user.email="rsi@local" commit -q -m ("dashboard " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
    git push -f $remote gh-pages
    Remove-Item -Recurse -Force ".git"
}
finally { Pop-Location }

Write-Host "Done. Pages will update in ~1 minute." -ForegroundColor Green
