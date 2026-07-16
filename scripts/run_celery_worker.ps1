# Start Celery worker for BOQ analysis (Windows).
# Requires Redis at redis://localhost:6379/0
# If you see "BOQ does not exist" on startup, clear stale queued tasks first:
#   wsl redis-cli FLUSHDB
Set-Location $PSScriptRoot\..\backend
& ..\.venv\Scripts\python.exe -m celery -A config worker --loglevel=info --pool=threads --concurrency=4
