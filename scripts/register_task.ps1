# Registers a Windows Scheduled Task to run the RSI scanner once every
# weekday evening after the Indian market close (default 18:30 IST).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1

param(
    [string]$Time = "18:30",
    [string]$TaskName = "NSE_BSE_RSI_Scanner"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# Runs the scan AND publishes the fresh dashboard to GitHub Pages (gh-pages).
$deploy = Join-Path $root "scripts\deploy_pages.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -NoProfile -File `"$deploy`"" -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
# Restrict to Mon-Fri (Indian trading days; holidays are handled by the data
# layer — a holiday simply yields no new completed candle).
$trigger.DaysInterval = 1

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Daily NSE+BSE RSI(14) scan + Pages deploy" -Force

Write-Host "Registered task '$TaskName' to run daily at $Time (scan + deploy to Pages)."
Write-Host "Remove with:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
