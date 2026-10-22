$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$matches = rg -n --hidden `
    --glob '!.git/**' --glob '!.env' --glob '!**/.venv/**' --glob '!**/node_modules/**' `
    --glob '!frontend/dist/**' --glob '!submission/**' `
    '(sk-[A-Za-z0-9_-]{20,}|POLYV_APP_SECRET\s*=\s*[^\s#][^\r\n]+)' `
    . 2>$null

if ($LASTEXITCODE -eq 0 -and $matches) {
    Write-Host $matches
    throw 'Potential committed secret detected.'
}
if ($LASTEXITCODE -notin 0, 1) { throw 'Sensitive information scan failed.' }
Write-Host 'Sensitive information scan passed.' -ForegroundColor Green
$global:LASTEXITCODE = 0
