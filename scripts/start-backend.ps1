$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $projectRoot 'backend')
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

