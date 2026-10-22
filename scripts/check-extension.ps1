$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$extensionRoot = Join-Path $projectRoot 'extension'

$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $extensionRoot 'manifest.json') | ConvertFrom-Json
if ($manifest.manifest_version -ne 3) { throw 'Extension must use Manifest V3.' }
if (-not $manifest.content_scripts -or -not $manifest.content_scripts[0].js) {
    throw 'Extension content script is missing.'
}
if (-not ($manifest.content_scripts | Where-Object { $_.js -contains 'pairing.js' })) {
    throw 'Teacher-page pairing content script is missing.'
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
if ($content -notmatch 'pointerdown' -or $content -notmatch 'setPointerCapture') {
    throw 'Extension floating assistant must support bounded pointer dragging.'
}
if ($content -notmatch 'qp-disconnected' -or $content -notmatch 'fullscreenchange') {
    throw 'Extension must expose disconnected state and recover inside fullscreen pages.'
}
if ($content -notmatch 'ai_normalized_intent' -or $content -notmatch 'ai_semantic_reason') {
    throw 'Extension must display auditable teacher-only AI semantic hints.'
}
$background = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $extensionRoot 'background.js')
if ($background -notmatch 'chrome\.runtime\.onMessage' -or $background -notmatch '\bfetch\s*\(') {
    throw 'Extension background API bridge is missing.'
}
if ($background -notmatch 'isAllowedRequest' -or $background -notmatch 'saved\.sessionId') {
    throw 'Extension API bridge must enforce a route and bound-classroom allowlist.'
}
$pairing = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $extensionRoot 'pairing.js')
if ($pairing -notmatch 'chrome\.storage\.session' -or $pairing -match 'chrome\.storage\.local') {
    throw 'Teacher-page pairing must use non-persistent session storage.'
}
if ($pairing -notmatch 'ALLOWED_ORIGINS' -or $pairing -notmatch 'ALLOWED_API_BASES' -or $pairing -notmatch 'UUID_PATTERN') {
    throw 'Teacher-page pairing must validate origin, API base, and identifiers.'
}

node.exe (Join-Path $PSScriptRoot 'test-extension-pairing.mjs') (Join-Path $extensionRoot 'pairing.js')
if ($LASTEXITCODE -ne 0) { throw 'Extension teacher-page pairing behavior failed.' }

Write-Host 'Extension checks passed.' -ForegroundColor Green
