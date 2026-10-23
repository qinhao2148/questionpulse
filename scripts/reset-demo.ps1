$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sessionFile = Join-Path $projectRoot '.runtime\demo-session.json'

try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 2
} catch { throw 'Backend is not ready. Run scripts/start-demo.ps1 first.' }
if ($health.status -ne 'ready') { throw 'Backend readiness check failed.' }

Push-Location (Join-Path $projectRoot 'backend')
try { uv run python scripts/seed_demo.py --output $sessionFile | Out-Null }
finally { Pop-Location }

$demo = Get-Content -Raw -LiteralPath $sessionFile | ConvertFrom-Json
Write-Host 'A fresh demo classroom was created; previous evidence was preserved.' -ForegroundColor Green
Write-Host "Student: $($demo.student_url)"
Write-Host 'Teacher: run scripts/open-demo-teacher.ps1 to open the authorized teacher entry'
Write-Host "Report:  $($demo.report_url)"
