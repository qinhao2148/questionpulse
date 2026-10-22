$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$extensionRoot = Join-Path $projectRoot 'extension'

$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $extensionRoot 'manifest.json') | ConvertFrom-Json
if ($manifest.manifest_version -ne 3) { throw 'Extension must use Manifest V3.' }
if (-not $manifest.content_scripts -or -not $manifest.content_scripts[0].js) {
    throw 'Extension content script is missing.'
}
if ($manifest.background.service_worker -ne 'background.js') {
    throw 'Extension session-storage service worker is missing.'
}

Get-ChildItem -LiteralPath $extensionRoot -Filter '*.js' | ForEach-Object {
    node.exe --check $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Extension JavaScript syntax check failed: $($_.Name)" }
}

$forbidden = Select-String -Path (Join-Path $extensionRoot '*') -Pattern 'APP_SECRET|LLM_API_KEY|pushSecret' -SimpleMatch -ErrorAction SilentlyContinue
if ($forbidden) { throw 'Extension contains a forbidden secret field.' }

$content = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $extensionRoot 'content.js')
if ($content -match 'chrome\.storage\.local') {
    throw 'Teacher credentials must not use persistent chrome.storage.local.'
}
if ($content -notmatch 'chrome\.storage\.session') {
    throw 'Teacher credentials must use chrome.storage.session.'
}
if ($content -match '\bfetch\s*\(') {
    throw 'Content script must route API requests through the background service worker.'
}
$background = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $extensionRoot 'background.js')
if ($background -notmatch 'chrome\.runtime\.onMessage' -or $background -notmatch '\bfetch\s*\(') {
    throw 'Extension background API bridge is missing.'
}

Write-Host 'Extension checks passed.' -ForegroundColor Green
