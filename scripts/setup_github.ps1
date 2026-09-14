# One-time GitHub setup: creates a PUBLIC repo under your account, pushes the
# code, publishes the first dashboard to gh-pages, and enables GitHub Pages.
#
# PREREQUISITE: the GitHub CLI must be installed and authenticated:
#     winget install --id GitHub.cli -e
#     gh auth login --git-protocol https --web
#
# Usage:
#     powershell -ExecutionPolicy Bypass -File scripts\setup_github.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\setup_github.ps1 -Repo my-name

param(
    [string]$Repo = "nse-bse-rsi-scanner"
)

# Continue (not Stop): native git/gh write to stderr, which PowerShell 5.1 turns
# into error records that would abort under 'Stop'. Check $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
function Fail($msg) { Write-Host $msg -ForegroundColor Red; exit 1 }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Fail "GitHub CLI 'gh' not found. Install: winget install --id GitHub.cli -e ; then: gh auth login"
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { Fail "gh is not authenticated. Run: gh auth login --git-protocol https --web" }

$owner = (gh api user --jq ".login")
Write-Host "GitHub user: $owner" -ForegroundColor Cyan

# --- ensure a local commit exists ----------------------------------------
if (-not (Test-Path ".git")) { git init -q }
git add -A
git -c user.name="$owner" -c user.email="$owner@users.noreply.github.com" commit -q -m "Initial commit: NSE+BSE RSI scanner" *> $null
git branch -M main

# --- create the remote repo and push main --------------------------------
gh repo view "$owner/$Repo" *> $null
$exists = ($LASTEXITCODE -eq 0)
if (-not $exists) {
    Write-Host "Creating public repo $owner/$Repo ..." -ForegroundColor Cyan
    gh repo create "$Repo" --public --source . --remote origin --push
    if ($LASTEXITCODE -ne 0) { Fail "gh repo create failed (exit $LASTEXITCODE)" }
} else {
    Write-Host "Repo already exists; pushing main." -ForegroundColor Yellow
    if (-not (git remote get-url origin)) { git remote add origin "https://github.com/$owner/$Repo.git" }
    git push -u origin main
}

# --- publish first dashboard to gh-pages ----------------------------------
if (-not (Test-Path (Join-Path $root "site\index.html"))) {
    Write-Host "No site\ yet - running a scan first (this can take several minutes)..." -ForegroundColor Cyan
    & (Join-Path $root ".venv\Scripts\python.exe") -m rsi_scanner.scan --use-cache --fundamentals-scope signal
}
& (Join-Path $root "scripts\deploy_pages.ps1") -SkipScan

# --- enable GitHub Pages from the gh-pages branch -------------------------
Write-Host "Enabling GitHub Pages (branch gh-pages, root)..." -ForegroundColor Cyan
gh api -X POST "repos/$owner/$Repo/pages" -f "source[branch]=gh-pages" -f "source[path]=/" *> $null
gh api -X PUT  "repos/$owner/$Repo/pages" -f "source[branch]=gh-pages" -f "source[path]=/" *> $null

$url = "https://$owner.github.io/$Repo/"
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Repo : https://github.com/$owner/$Repo" -ForegroundColor Green
Write-Host " Pages: $url" -ForegroundColor Green
Write-Host " (Pages can take 1-2 minutes to go live on first setup.)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Next: register the daily auto-update task:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1"
