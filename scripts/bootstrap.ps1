$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

Set-Location $projectRoot

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}

pnpm install
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
Push-Location backend
try {
    uv sync --python 3.11
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
}
finally {
    Pop-Location
}

Write-Host 'QuestionPulse dependencies are ready.' -ForegroundColor Green

