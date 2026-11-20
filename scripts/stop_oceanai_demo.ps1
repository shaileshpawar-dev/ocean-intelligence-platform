<#
.SYNOPSIS
    Stop the OceanAI backend started by scripts\start_oceanai_demo.ps1.

.DESCRIPTION
    Reads logs\demo\backend.pid and stops only a process tree that is verified
    to be the OceanAI uvicorn backend for this repository. If the PID file is
    missing or the process does not match, nothing is stopped.

    The PostGIS container and its volume are intentionally left running. This
    script never runs docker compose down, never removes volumes, and never
    touches unrelated services.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\stop_oceanai_demo.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $RepoRoot "logs\demo\backend.pid"

Write-Host "OceanAI demo shutdown" -ForegroundColor Green

if (-not (Test-Path $PidFile)) {
    Write-Host "No backend PID file found at $PidFile." -ForegroundColor Yellow
    Write-Host "The backend was not started by this script, so nothing will be stopped."
    Write-Host "The database container is left running."
    exit 0
}

$backendPid = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
if (-not $backendPid -or $backendPid -notmatch '^\d+$') {
    Write-Host "The PID file does not contain a valid process ID. Nothing will be stopped." -ForegroundColor Yellow
    exit 1
}

$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$backendPid" -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Host "PID $backendPid is no longer running. Removing the stale PID file."
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host "The database container is left running."
    exit 0
}

$commandLine = [string]$proc.CommandLine
$expectedRepo = $RepoRoot.ToLowerInvariant()
$isOceanAi = $commandLine.ToLowerInvariant().Contains("uvicorn") -and
    $commandLine.ToLowerInvariant().Contains("app.main:app") -and
    $commandLine.ToLowerInvariant().Contains($expectedRepo)
if (-not $isOceanAi) {
    Write-Host "PID $backendPid does not match the OceanAI backend command line. Nothing will be stopped." -ForegroundColor Yellow
    Write-Host "Command line: $commandLine"
    exit 1
}

$children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$backendPid" -ErrorAction SilentlyContinue)
foreach ($child in $children) {
    Write-Host "Stopping child process $($child.ProcessId) ($($child.Name))..."
    Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host "Stopping OceanAI backend PID $backendPid..."
Stop-Process -Id $backendPid -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 1
$stillListening = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($stillListening) {
    Write-Host "Port 8000 is still listening. Inspect the remaining process before stopping anything else." -ForegroundColor Yellow
    exit 1
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "OceanAI backend stopped." -ForegroundColor Green
Write-Host "The PostGIS container and database volume were left running and untouched."
