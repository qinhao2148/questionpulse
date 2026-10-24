$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot '.runtime\demo-processes.json'

if (Test-Path -LiteralPath $pidFile) {
    $processes = Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json
    foreach ($processId in @($processes.backend_pid, $processes.frontend_pid, $processes.watch_client_pid)) {
        if (-not $processId) { continue }
        taskkill.exe /PID $processId /T /F 2>$null | Out-Null
    }
    Remove-Item -LiteralPath $pidFile
}

foreach ($port in 5173, 8000, 15021) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if ($processInfo.CommandLine -match 'vite|uvicorn|webpack|knowledge_worker') {
            Stop-Process -Id $listener.OwningProcess -Force
        }
    }
}

Write-Host 'QuestionPulse demo services stopped. MySQL remains running.' -ForegroundColor Green
