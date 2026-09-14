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

# NB: keep ErrorActionPreference at Continue. Native git/gh write progress to
# stderr, which Windows PowerShell 5.1 turns into error records; under 'Stop'
# that aborts the script even on success. We check $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"

function Fail($msg) { Write-Host $msg -ForegroundColor Red; exit 1 }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if (-not $SkipScan) {
    Write-Host "Running scan..." -ForegroundColor Cyan
    & $python -m rsi_scanner.scan $ScanArgs.Split(" ")
    if ($LASTEXITCODE -ne 0) { Fail "Scan failed (exit $LASTEXITCODE)" }
}

$site = Join-Path $root "site"
if (-not (Test-Path (Join-Path $site "index.html"))) { Fail "site\index.html not found - run a scan first." }

$remote = (git -C $root remote get-url origin)
if (-not $remote) { Fail "No 'origin' remote. Run scripts\setup_github.ps1 first." }

Write-Host "Publishing site\ to gh-pages on $remote ..." -ForegroundColor Cyan
Push-Location $site
try {
    if (Test-Path ".git") { Remove-Item -Recurse -Force ".git" }
    git init -q
    git checkout -q -b gh-pages
    New-Item -ItemType File -Path ".nojekyll" -Force | Out-Null   # serve files as-is
    git add -A
    git -c user.name="rsi-scanner" -c user.email="rsi@local" commit -q -m ("dashboard " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
    git push -f $remote gh-pages
    if ($LASTEXITCODE -ne 0) { Fail "git push to gh-pages failed (exit $LASTEXITCODE)" }
}
finally {
    if (Test-Path ".git") { Remove-Item -Recurse -Force ".git" }
    Pop-Location
}

Write-Host "Done. Pages will update in ~1 minute." -ForegroundColor Green
