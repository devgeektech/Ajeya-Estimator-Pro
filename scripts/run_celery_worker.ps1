# Start Celery worker for BOQ analysis (Windows).
# Requires Redis at redis://localhost:6379/0
# Concurrent BOQ analyses ~= CELERY_WORKER_CONCURRENCY (default 8).
# If you see "BOQ does not exist" on startup, clear stale queued tasks first:
#   wsl redis-cli FLUSHDB
$concurrency = if ($env:CELERY_WORKER_CONCURRENCY) { $env:CELERY_WORKER_CONCURRENCY } else { "8" }
Set-Location $PSScriptRoot\..\backend
& ..\.venv\Scripts\python.exe -m celery -A config worker --loglevel=info --pool=threads --concurrency=$concurrency
