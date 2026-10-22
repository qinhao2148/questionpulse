$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
$configPath = Join-Path $runtimeDir 'polyv-push.json'
$videoPath = Join-Path $runtimeDir 'questionpulse-live-loop.mp4'
$pidPath = Join-Path $runtimeDir 'polyv-live.pid'
$stdoutPath = Join-Path $runtimeDir 'polyv-live.stdout.log'
$stderrPath = Join-Path $runtimeDir 'polyv-live.stderr.log'

if (-not (Test-Path -LiteralPath $configPath)) { throw 'Missing local POLYV push configuration.' }
if (-not (Test-Path -LiteralPath $videoPath)) { throw 'Missing QuestionPulse live demo video.' }
if (Test-Path -LiteralPath $pidPath) {
    $existingPid = [int](Get-Content -Raw -LiteralPath $pidPath)
    if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
        throw "POLYV demo stream is already running (PID $existingPid)."
    }
}

$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
if (-not $config.pushUrl -or -not $config.pushSecret) { throw 'POLYV push address is incomplete.' }
$pushTarget = "$($config.pushUrl)$($config.pushSecret)"
$arguments = @(
    '-hide_banner', '-loglevel', 'error', '-nostats', '-re',
    '-stream_loop', '-1', '-i', $videoPath,
    '-c:v', 'copy', '-c:a', 'copy', '-f', 'flv', $pushTarget
)
$process = Start-Process -FilePath 'ffmpeg.exe' -ArgumentList $arguments `
    -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
$process.Id | Set-Content -LiteralPath $pidPath -Encoding ascii
Start-Sleep -Seconds 2
if ($process.HasExited) { throw 'POLYV demo stream failed to start.' }
Write-Host "QuestionPulse POLYV demo stream started (PID $($process.Id))." -ForegroundColor Green

