$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $projectRoot '.runtime\polyv-live.pid'

if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Host 'QuestionPulse POLYV demo stream is not running.'
    exit 0
}
$streamPid = [int](Get-Content -Raw -LiteralPath $pidPath)
$process = Get-Process -Id $streamPid -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $streamPid
    $process.WaitForExit(5000)
}
Remove-Item -LiteralPath $pidPath -Force
Write-Host 'QuestionPulse POLYV demo stream stopped.' -ForegroundColor Green

