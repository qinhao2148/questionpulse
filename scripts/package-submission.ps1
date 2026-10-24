$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$submissionDir = Join-Path $projectRoot 'submission'
$archive = Join-Path $submissionDir 'questionpulse-source.zip'

& (Join-Path $PSScriptRoot 'check-sensitive.ps1')
if (-not $?) { throw 'Sensitive information scan failed.' }

New-Item -ItemType Directory -Force -Path $submissionDir | Out-Null
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive }

Push-Location $projectRoot
try {
    tar.exe -a -cf $archive `
        --exclude=.git --exclude=.env --exclude=.runtime `
        --exclude=node_modules --exclude=frontend/node_modules --exclude=frontend/dist `
        --exclude=polyv-watch-client/node_modules --exclude=polyv-watch-client/dist `
        --exclude=backend/.venv --exclude='**/__pycache__' --exclude='*.pyc' `
        --exclude='.pytest_cache' --exclude='.ruff_cache' `
        README.md .env.example .editorconfig .gitattributes .gitignore compose.yaml `
        package.json pnpm-lock.yaml pnpm-workspace.yaml backend frontend scripts docs fixtures `
        extension polyv-watch-client `
        assets/submission/README.md assets/submission/questionpulse-team-poster-ray-v7.png
    if ($LASTEXITCODE -ne 0) { throw 'Submission archive creation failed.' }
}
finally { Pop-Location }

$listing = tar.exe -tf $archive
if ($listing -match '(^|/)\.env$|node_modules|\.venv|\.runtime') {
    throw 'Submission archive contains a forbidden runtime or secret path.'
}
foreach ($required in @('extension/manifest.json', 'polyv-watch-client/package.json')) {
    if ($listing -notmatch [regex]::Escape($required)) {
        throw "Submission archive is missing required deliverable: $required"
    }
}
Write-Host "Submission package ready: $archive" -ForegroundColor Green
Write-Host "Size: $([math]::Round((Get-Item -LiteralPath $archive).Length / 1MB, 2)) MB"
