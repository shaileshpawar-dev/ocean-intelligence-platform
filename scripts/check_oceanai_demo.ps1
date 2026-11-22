<#
.SYNOPSIS
    Check the local OceanAI faculty demonstration without changing any state.

.DESCRIPTION
    Verifies Docker, the PostGIS container, database connectivity, backend
    health, the built browser console, and the key API endpoints used in the
    demonstration. Also checks that held-out split/SAFE identifiers are not
    exposed by the public candidate API and that the demo images are served.

    This script is read-only. It does not start, stop, seed, or modify anything.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check_oceanai_demo.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
$BaseUrl = "http://127.0.0.1:8000"
$results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$Name, [bool]$Ok, [string]$Detail) {
    $results.Add([pscustomobject]@{ Name = $Name; Ok = $Ok; Detail = $Detail })
    if ($Ok) {
        Write-Host ("  PASS  {0}: {1}" -f $Name, $Detail) -ForegroundColor Green
    } else {
        Write-Host ("  FAIL  {0}: {1}" -f $Name, $Detail) -ForegroundColor Red
    }
}

function Invoke-Json([string]$Path) {
    return Invoke-RestMethod -Uri ($BaseUrl + $Path) -TimeoutSec 20 -UseBasicParsing
}

function Invoke-Page([string]$Url) {
    return Invoke-WebRequest -Uri $Url -TimeoutSec 20 -UseBasicParsing
}

Write-Host "OceanAI demo readiness check" -ForegroundColor Green
Write-Host "Repository: $RepoRoot"

Write-Host ""
Write-Host "==> Docker and database" -ForegroundColor Cyan
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Add-Result "Docker CLI" $false "docker command not found"
} else {
    $version = (& docker info --format "{{.ServerVersion}}" 2>&1 | Out-String).Trim()
    Add-Result "Docker daemon" ($LASTEXITCODE -eq 0 -and $version) "server=$version"

    $containerId = (& docker compose -f $ComposeFile ps -q db 2>$null | Out-String).Trim()
    if (-not $containerId) {
        $containerId = (& docker ps -a --filter "name=ocean-intelligence-platform-db-1" --format "{{.ID}}" 2>$null | Out-String).Trim()
    }
    if (-not $containerId) {
        Add-Result "PostGIS container" $false "container not found"
    } else {
        $status = (& docker inspect -f "{{.State.Status}}" $containerId 2>$null | Out-String).Trim()
        $health = (& docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $containerId 2>$null | Out-String).Trim()
        Add-Result "PostGIS container" ($status -eq "running") "status=$status health=$health id=$($containerId.Substring(0, [Math]::Min(12, $containerId.Length)))"
    }
}

if (Test-Path $Python) {
    $env:PYTHONPATH = $BackendDir
    Push-Location $BackendDir
    try {
        $dbOutput = (& $Python -c "from app.core.database import engine; from sqlalchemy import text; c=engine.connect(); print(c.execute(text('select count(*) from water_quality_observations')).scalar()); print(c.execute(text('select count(*) from sar_candidates')).scalar()); print(c.execute(text('select count(*) from sar_candidate_reviews')).scalar()); c.close()" 2>&1 | Out-String).Trim()
        $dbExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $dbLines = @($dbOutput -split "`r?`n" | Where-Object { $_ -match '^\d+$' })
    if ($dbExit -eq 0 -and $dbLines.Count -ge 3) {
        Add-Result "Database contents" ([int]$dbLines[0] -ge 4601153 -and [int]$dbLines[1] -ge 300 -and [int]$dbLines[2] -ge 8) "water_observations=$($dbLines[0]) sar_candidates=$($dbLines[1]) reviews=$($dbLines[2])"
    } else {
        Add-Result "Database contents" $false "query failed: $dbOutput"
    }
} else {
    Add-Result "Python environment" $false "missing $Python"
}

Write-Host ""
Write-Host "==> Backend and browser console" -ForegroundColor Cyan
try {
    $health = Invoke-Json "/api/v1/health"
    Add-Result "Health API" ($health.status -eq "ok" -and $health.app_name -eq "Ocean Intelligence Platform") "status=$($health.status) app=$($health.app_name) demo_mode=$($health.demo_mode)"
    $dbComponent = $health.components | Where-Object { $_.name -eq "database" }
    Add-Result "Database component" ($dbComponent -and $dbComponent.available) ($dbComponent.detail)
}
catch {
    Add-Result "Health API" $false $_.Exception.Message
}

try {
    $app = Invoke-Page ($BaseUrl + "/app")
    Add-Result "Browser console" ($app.StatusCode -eq 200 -and $app.Content -match 'id="root"') "HTTP $($app.StatusCode)"
}
catch {
    Add-Result "Browser console" $false $_.Exception.Message
}

try {
    $docs = Invoke-Page ($BaseUrl + "/docs")
    Add-Result "API docs" ($docs.StatusCode -eq 200) "HTTP $($docs.StatusCode)"
}
catch {
    Add-Result "API docs" $false $_.Exception.Message
}

$spaIndex = Join-Path $RepoRoot "backend\app\static\app\index.html"
if (Test-Path $spaIndex) {
    $newestSource = Get-ChildItem -Path (Join-Path $RepoRoot "frontend\src") -Recurse -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    $stale = $newestSource -and $newestSource.LastWriteTime -gt (Get-Item $spaIndex).LastWriteTime
    Add-Result "Console build freshness" (-not $stale) $(if ($stale) { "frontend/src is newer; rebuild required" } else { "built console is current" })
} else {
    Add-Result "Console build freshness" $false "backend/app/static/app/index.html missing"
}

Write-Host ""
Write-Host "==> Demo APIs and images" -ForegroundColor Cyan
try {
    $water = Invoke-Json "/api/v1/water-overview"
    Add-Result "India water overview" ($water.water_bodies -gt 2000 -and $water.observations -gt 4000000) "water_bodies=$($water.water_bodies) observations=$($water.observations)"
}
catch {
    Add-Result "India water overview" $false $_.Exception.Message
}

try {
    $summary = Invoke-Json "/api/v1/sar-candidates/summary"
    Add-Result "Candidate summary" ($summary.total_candidates -ge 300) "total=$($summary.total_candidates) awaiting=$($summary.awaiting_analyst_review) reviewed=$($summary.reviewed_candidates)"
}
catch {
    Add-Result "Candidate summary" $false $_.Exception.Message
}

try {
    $candidate = Invoke-Json "/api/v1/sar-candidates/cand_s1_0036"
    $keys = @($candidate.PSObject.Properties.Name)
    $leaks = @($keys | Where-Object { $_ -in @("split", "safe_scene", "ground_truth") })
    Add-Result "Candidate detail" ($candidate.candidate_id -eq "cand_s1_0036") "confidence_is_calibrated=$($candidate.confidence_is_calibrated)"
    Add-Result "No held-out identifiers" ($leaks.Count -eq 0) $(if ($leaks.Count -eq 0) { "split/safe_scene/ground_truth absent" } else { "exposed: $($leaks -join ', ')" })
}
catch {
    Add-Result "Candidate detail" $false $_.Exception.Message
}

try {
    $img = Invoke-Page ($BaseUrl + "/api/v1/sar-candidates/cand_s1_0036/image")
    Add-Result "Candidate patch image" ($img.StatusCode -eq 200 -and $img.Headers["Content-Type"] -match "image") "HTTP $($img.StatusCode) type=$($img.Headers['Content-Type'])"
}
catch {
    Add-Result "Candidate patch image" $false $_.Exception.Message
}

try {
    $opt = Invoke-Page ($BaseUrl + "/api/v1/sar-candidates/cand_s1_0036/optical-evidence/1/image/rgb")
    Add-Result "Optical product image" ($opt.StatusCode -eq 200 -and $opt.Headers["Content-Type"] -match "image") "HTTP $($opt.StatusCode) type=$($opt.Headers['Content-Type'])"
}
catch {
    Add-Result "Optical product image" $false $_.Exception.Message
}

try {
    $scenes = Invoke-Json "/api/v1/sar-scenes?limit=200"
    Add-Result "SAR scene inventory" ($scenes.total -ge 148 -and $scenes.scenes.Count -ge 148) "total=$($scenes.total) returned=$($scenes.scenes.Count)"
}
catch {
    Add-Result "SAR scene inventory" $false $_.Exception.Message
}

try {
    $models = Invoke-Json "/api/v1/models"
    $modelCount = if ($models.models) { $models.models.Count } else { $models.Count }
    Add-Result "Model registry" ($modelCount -ge 2) "models=$modelCount"
}
catch {
    Add-Result "Model registry" $false $_.Exception.Message
}

try {
    $drift = Invoke-Json "/api/v1/drift"
    Add-Result "ML drift endpoint" ($null -ne $drift) "response received"
}
catch {
    Add-Result "ML drift endpoint" $false $_.Exception.Message
}

Write-Host ""
$failed = @($results | Where-Object { -not $_.Ok })
if ($failed.Count -eq 0) {
    Write-Host "ALL CHECKS PASSED ($($results.Count)/$($results.Count))" -ForegroundColor Green
    Write-Host "Open: http://127.0.0.1:8000/app"
    exit 0
} else {
    Write-Host "$($failed.Count) of $($results.Count) checks failed." -ForegroundColor Red
    $failed | ForEach-Object { Write-Host ("  - {0}: {1}" -f $_.Name, $_.Detail) -ForegroundColor Red }
    exit 1
}
