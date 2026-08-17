# Start Celery worker for BOQ analysis (Windows) with auto-restart.
# Requires Redis at redis://localhost:6379/0
#
# Keep this window open while using Analyse. If the worker exits (Ctrl-C,
# crash, or Windows threads pool shutdown), it restarts automatically so
# queued BOQ jobs are not left stuck in PROCESSING.
#
# Concurrent BOQ analyses ~= CELERY_WORKER_CONCURRENCY (default 4 on Windows).
# If you see "BOQ does not exist" on startup, clear stale queued tasks first:
#   wsl redis-cli FLUSHDB

$ErrorActionPreference = "Continue"
$env:PYTHONUNBUFFERED = "1"
$concurrency = if ($env:CELERY_WORKER_CONCURRENCY) { $env:CELERY_WORKER_CONCURRENCY } else { "4" }
$pool = if ($env:CELERY_WORKER_POOL) { $env:CELERY_WORKER_POOL } else { "threads" }
$restartDelaySec = 3

Set-Location $PSScriptRoot\..\backend
$python = Join-Path (Resolve-Path ..\.venv\Scripts).Path "python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Python venv not found at $python"
    exit 1
}

# Stop leftover workers from earlier terminals so nodenames do not collide.
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'celery -A config worker') } |
    ForEach-Object {
        Write-Host ("Stopping leftover Celery pid={0}" -f $_.ProcessId)
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 1

Write-Host "BOQ_AI Celery worker (pool=$pool concurrency=$concurrency)"
Write-Host "Auto-restart enabled. Press Ctrl+C twice to stop."
Write-Host "Redis must be running at redis://localhost:6379/0"
Write-Host "Watch THIS terminal for BOQ Analyse log lines while analysing."
Write-Host "Run only ONE Celery terminal - extras cause DuplicateNodenameWarning."
Write-Host ""

while ($true) {
    # Unique nodename per process (avoids DuplicateNodenameWarning).
    $nodeName = "boq-" + $PID + "@" + $env:COMPUTERNAME
    $stamp = Get-Date -Format "HH:mm:ss"
    Write-Host "[$stamp] Starting Celery worker as $nodeName..."
    & $python -m celery -A config worker --loglevel=info --pool=$pool --concurrency=$concurrency --hostname=$nodeName
    $code = $LASTEXITCODE
    $stamp = Get-Date -Format "HH:mm:ss"
    Write-Host "[$stamp] Celery exited (code=$code). Restarting in $restartDelaySec s..."
    Write-Host "Analyse will pause until the worker is back. Do not close this window."
    Start-Sleep -Seconds $restartDelaySec
}
