$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
$pidFile = Join-Path $runtimeDir 'demo-processes.json'
$sessionFile = Join-Path $runtimeDir 'demo-session.json'

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
Set-Location $projectRoot

docker compose up -d mysql
if ($LASTEXITCODE -ne 0) { throw 'MySQL startup failed.' }

Push-Location (Join-Path $projectRoot 'backend')
try {
    uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
}
finally { Pop-Location }

if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is already in use. Run scripts/stop-demo.ps1 or release the port.'
}
if (Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue) {
    throw 'Port 5173 is already in use. Run scripts/stop-demo.ps1 or release the port.'
}
if (Get-NetTCPConnection -State Listen -LocalPort 15021 -ErrorAction SilentlyContinue) {
    throw 'Port 15021 is already in use. Run scripts/stop-demo.ps1 or release the port.'
}

$backend = Start-Process -FilePath 'uv' -ArgumentList @(
    'run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'
) -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru
$frontend = Start-Process -FilePath 'pnpm.cmd' -ArgumentList @(
    '--dir', 'frontend', 'dev', '--host', '127.0.0.1'
) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
$watchClient = Start-Process -FilePath 'npm.cmd' -ArgumentList @(
    'run', 'dev'
) -WorkingDirectory (Join-Path $projectRoot 'polyv-watch-client') -WindowStyle Hidden -PassThru

@{ backend_pid = $backend.Id; frontend_pid = $frontend.Id; watch_client_pid = $watchClient.Id } |
    ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding utf8

$ready = $false
for ($attempt = 0; $attempt -lt 360; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 2
        $frontendStatus = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 2
        $watchStatus = Invoke-WebRequest -Uri 'http://127.0.0.1:15021' -UseBasicParsing -TimeoutSec 2
        if ($health.status -eq 'ready' -and $frontendStatus.StatusCode -eq 200 -and $watchStatus.StatusCode -eq 200) {
            $ready = $true
            break
        }
    }
    catch { Start-Sleep -Milliseconds 500 }
}
if (-not $ready) { throw 'Demo services did not become ready within 180 seconds.' }

Push-Location (Join-Path $projectRoot 'backend')
try {
    uv run python scripts/seed_demo.py --output $sessionFile | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Demo seed failed.' }
}
finally { Pop-Location }

$demo = Get-Content -Raw -LiteralPath $sessionFile | ConvertFrom-Json
Write-Host 'QuestionPulse demo is ready.' -ForegroundColor Green
Write-Host "Student: $($demo.student_url)"
Write-Host 'Teacher: open http://127.0.0.1:5173/ and sign in'
Write-Host "Report:  $($demo.report_url)"
