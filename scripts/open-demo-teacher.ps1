$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sessionFile = Join-Path $projectRoot '.runtime\demo-session.json'

if (-not (Test-Path -LiteralPath $sessionFile)) {
    throw 'Demo metadata is missing. Run scripts/start-demo.ps1 first.'
}

$demo = Get-Content -Raw -LiteralPath $sessionFile | ConvertFrom-Json
if (-not $demo.teacher_bootstrap_url) {
    throw 'Demo metadata is outdated. Run scripts/reset-demo.ps1 once.'
}

# The credential is carried in a URL fragment, which is not sent to the web server,
# and TeacherPage removes it immediately after saving it in sessionStorage.
Start-Process -FilePath $demo.teacher_bootstrap_url
