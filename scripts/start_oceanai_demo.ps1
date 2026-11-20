<#
.SYNOPSIS
    Start the OceanAI faculty demonstration on this Windows machine.

.DESCRIPTION
    - Verifies Docker Desktop and the existing PostGIS container.
    - Starts the existing container only if it is stopped (never recreates it).
    - Waits for PostgreSQL health and verifies the SQLAlchemy connection.
    - Starts the FastAPI backend from the existing virtual environment.
    - Verifies the health endpoint, the SPA and key demo API routes.
    - Does not start a second backend if one is already healthy on port 8000.

    The React console is built into backend/app/static/app and is served by
    FastAPI at /app, so there is no separate frontend process to start.

.PARAMETER RebuildFrontend
    Rebuild the React console before starting. Use after changing frontend/src.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_oceanai_demo.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_oceanai_demo.ps1 -RebuildFrontend
#>

[CmdletBinding()]
param(
    [switch]$RebuildFrontend
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
$SpaIndex = Join-Path $RepoRoot "backend\app\static\app\index.html"
$LogDir = Join-Path $RepoRoot "logs\demo"
$PidFile = Join-Path $LogDir "backend.pid"
$HealthUrl = "http://127.0.0.1:8000/api/v1/health"
$AppUrl = "http://127.0.0.1:8000/app"
$DocsUrl = "http://127.0.0.1:8000/docs"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "FAILED: $Message" -ForegroundColor Red
    exit 1
}

function Test-BackendHealth {
    try {
        $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 5 -UseBasicParsing
        return ($health.status -eq "ok" -and $health.app_name -eq "Ocean Intelligence Platform")
    }
    catch {
        return $false
    }
}

function Show-LogTail([string]$Path, [int]$Lines = 20) {
    if (Test-Path $Path) {
        Write-Host "--- $Path (last $Lines lines) ---" -ForegroundColor DarkYellow
        Get-Content -Path $Path -Tail $Lines -ErrorAction SilentlyContinue
        Write-Host "--- end log ---" -ForegroundColor DarkYellow
    }
}

Write-Host "OceanAI demo startup" -ForegroundColor Green
Write-Host "Repository: $RepoRoot"

if (-not (Test-Path $Python)) {
    Fail "Python virtual environment not found at $Python. Restore .venv before running the demo."
}
if (-not (Test-Path $BackendDir)) {
    Fail "Backend directory not found at $BackendDir."
}
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Step "Checking Docker"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Fail "Docker CLI was not found. Start Docker Desktop, then rerun this script."
}
$dockerVersion = (& docker info --format "{{.ServerVersion}}" 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $dockerVersion) {
    Fail "Docker Desktop is not running or the daemon is unreachable. Start Docker Desktop, wait for it to finish starting, then rerun this script."
}
Write-Host "Docker server: $dockerVersion"

Write-Step "Checking the existing PostGIS container"
$containerId = (& docker compose -f $ComposeFile ps -q db 2>$null | Out-String).Trim()
if (-not $containerId) {
    $containerId = (& docker ps -a --filter "name=ocean-intelligence-platform-db-1" --format "{{.ID}}" 2>$null | Out-String).Trim()
}
if (-not $containerId) {
    Fail "The OceanAI database container was not found. This script will not create or recreate it. Use docker compose up -d db manually, then rerun."
}

$status = (& docker inspect -f "{{.State.Status}}" $containerId 2>$null | Out-String).Trim()
if ($status -ne "running") {
    Write-Host "Database container is '$status'; starting the existing container (no recreation)."
    & docker start $containerId | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not start the existing database container $containerId."
    }
} else {
    Write-Host "Database container is already running."
}

Write-Step "Waiting for PostgreSQL readiness"
$deadline = (Get-Date).AddSeconds(120)
$dbReady = $false
while ((Get-Date) -lt $deadline) {
    $healthStatus = (& docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $containerId 2>$null | Out-String).Trim()
    if ($healthStatus -eq "healthy") {
        $dbReady = $true
        break
    }
    if ($healthStatus -eq "none") {
        & docker exec $containerId pg_isready 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $dbReady = $true
            break
        }
    }
    Start-Sleep -Seconds 2
}
if (-not $dbReady) {
    Fail "PostgreSQL did not become healthy within 120 seconds. Check 'docker ps' and 'docker logs $containerId'."
}
Write-Host "PostgreSQL is healthy."

Write-Step "Verifying database connectivity through the backend settings"
Push-Location $BackendDir
try {
    $dbCheck = (& $Python -c "from app.core.database import engine; from sqlalchemy import text; c=engine.connect(); print(c.execute(text('select 1')).scalar()); c.close()" 2>&1 | Out-String).Trim()
    $dbExit = $LASTEXITCODE
}
finally {
    Pop-Location
}
if ($dbExit -ne 0 -or $dbCheck -notmatch "1") {
    Fail "Database connectivity check failed. Output: $dbCheck"
}
Write-Host "Database connection OK."

Write-Step "Checking the backend on port 8000"
$alreadyHealthy = Test-BackendHealth
if ($alreadyHealthy) {
    Write-Host "A healthy OceanAI backend is already running; it will be reused (no duplicate process)."
} else {
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Fail "Port 8000 is already in use, but the OceanAI health check failed. Stop the process using port 8000 or inspect it before rerunning. This script will not kill an unrelated process."
    }

    Write-Host "Starting FastAPI with the existing virtual environment..."
    $outLog = Join-Path $LogDir "backend.out.log"
    $errLog = Join-Path $LogDir "backend.err.log"
    $proc = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru `
        -WindowStyle Hidden
    Set-Content -Path $PidFile -Value $proc.Id

    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        if (Test-BackendHealth) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not (Test-BackendHealth)) {
        Show-LogTail $errLog
        Show-LogTail $outLog
        Fail "The backend did not become healthy within 90 seconds. See the logs above."
    }
    Write-Host "Backend started (PID $($proc.Id))."
}

Write-Step "Checking the browser console build"
if ($RebuildFrontend -or -not (Test-Path $SpaIndex)) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Fail "The browser console is missing and npm was not found. Install Node.js or restore backend/app/static/app."
    }
    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "Installing frontend dependencies..."
        Push-Location $FrontendDir
        try {
            & npm install
            if ($LASTEXITCODE -ne 0) {
                Fail "npm install failed."
            }
        }
        finally {
            Pop-Location
        }
    }
    Write-Host "Building the React console..."
    Push-Location $FrontendDir
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            Fail "Frontend build failed."
        }
    }
    finally {
        Pop-Location
    }
} else {
    $newestSource = Get-ChildItem -Path (Join-Path $FrontendDir "src") -Recurse -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    $buildTime = (Get-Item $SpaIndex).LastWriteTime
    if ($newestSource -and $newestSource.LastWriteTime -gt $buildTime) {
        Write-Warning "frontend/src is newer than the built console. Run this script with -RebuildFrontend before presenting."
    }
    Write-Host "Browser console build found."
}

Write-Step "Verifying demo URLs and endpoints"
$checks = @()
try {
    $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 10 -UseBasicParsing
    $checks += [pscustomobject]@{ Name = "Health API"; Ok = ($health.status -eq "ok" -and $health.app_name -eq "Ocean Intelligence Platform"); Detail = "status=$($health.status), app=$($health.app_name), demo_mode=$($health.demo_mode)" }
}
catch {
    $checks += [pscustomobject]@{ Name = "Health API"; Ok = $false; Detail = $_.Exception.Message }
}
try {
    $app = Invoke-WebRequest -Uri $AppUrl -TimeoutSec 15 -UseBasicParsing
    $checks += [pscustomobject]@{ Name = "Browser console"; Ok = ($app.StatusCode -eq 200 -and $app.Content -match 'id="root"'); Detail = "HTTP $($app.StatusCode)" }
}
catch {
    $checks += [pscustomobject]@{ Name = "Browser console"; Ok = $false; Detail = $_.Exception.Message }
}
try {
    $docs = Invoke-WebRequest -Uri $DocsUrl -TimeoutSec 15 -UseBasicParsing
    $checks += [pscustomobject]@{ Name = "API docs"; Ok = ($docs.StatusCode -eq 200); Detail = "HTTP $($docs.StatusCode)" }
}
catch {
    $checks += [pscustomobject]@{ Name = "API docs"; Ok = $false; Detail = $_.Exception.Message }
}
try {
    $candidate = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/sar-candidates/cand_s1_0036" -TimeoutSec 15 -UseBasicParsing
    $checks += [pscustomobject]@{ Name = "Candidate detail"; Ok = ($candidate.candidate_id -eq "cand_s1_0036"); Detail = "confidence uncalibrated=$(-not $candidate.confidence_is_calibrated)" }
}
catch {
    $checks += [pscustomobject]@{ Name = "Candidate detail"; Ok = $false; Detail = $_.Exception.Message }
}
try {
    $image = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/sar-candidates/cand_s1_0036/image" -TimeoutSec 15 -UseBasicParsing
    $checks += [pscustomobject]@{ Name = "Candidate patch image"; Ok = ($image.StatusCode -eq 200 -and $image.Headers["Content-Type"] -match "image"); Detail = "HTTP $($image.StatusCode), $($image.Headers['Content-Type'])" }
}
catch {
    $checks += [pscustomobject]@{ Name = "Candidate patch image"; Ok = $false; Detail = $_.Exception.Message }
}

$failed = $checks | Where-Object { -not $_.Ok }
$checks | ForEach-Object {
    if ($_.Ok) {
        Write-Host ("  PASS  {0}: {1}" -f $_.Name, $_.Detail) -ForegroundColor Green
    } else {
        Write-Host ("  FAIL  {0}: {1}" -f $_.Name, $_.Detail) -ForegroundColor Red
    }
}
if ($failed) {
    Fail "One or more demo URLs failed verification."
}

Write-Host ""
Write-Host "OceanAI demo is ready." -ForegroundColor Green
Write-Host "  Dashboard:        http://127.0.0.1:8000/app/overview"
Write-Host "  India Water:      http://127.0.0.1:8000/app/india"
Write-Host "  India Water Map:  http://127.0.0.1:8000/app/map"
Write-Host "  Candidate Review: http://127.0.0.1:8000/app/candidate-review"
Write-Host "  Candidate Detail: http://127.0.0.1:8000/app/candidate-review/cand_s1_0036"
Write-Host "  Ocean Map:        http://127.0.0.1:8000/app/ocean-map"
Write-Host "  AI Assistant:     http://127.0.0.1:8000/app/ai"
Write-Host "  Health:           http://127.0.0.1:8000/app/health"
Write-Host "  Models:           http://127.0.0.1:8000/app/models"
Write-Host "  Events:           http://127.0.0.1:8000/app/events"
Write-Host "  API docs:         http://127.0.0.1:8000/docs"
Write-Host ""
Write-Host "Demo data labels: AIS = DEMONSTRATION DATA, SAR full-scene = SIMULATED, optical products = SYNTHETIC, drift/impact = SIMULATION."
Write-Host "Logs: $LogDir"
Write-Host "Shutdown: powershell -ExecutionPolicy Bypass -File scripts\stop_oceanai_demo.ps1"
Write-Host "The database container is intentionally left running; no volume is modified."
