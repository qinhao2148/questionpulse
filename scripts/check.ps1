$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

Set-Location $projectRoot
pnpm typecheck:frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend typecheck failed.' }
pnpm build:frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
pnpm test:frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }

& (Join-Path $PSScriptRoot 'check-extension.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Extension check failed.' }

Push-Location backend
try {
    uv run alembic current --check-heads
    if ($LASTEXITCODE -ne 0) { throw 'Database is not at the latest migration head.' }
    uv run ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed.' }
    uv run pytest
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
}
finally {
    Pop-Location
}

Write-Host 'All scaffold checks passed.' -ForegroundColor Green

