#!/usr/bin/env bash
# Start Celery worker for BOQ analysis.
# Requires Redis at redis://localhost:6379/0
# Concurrent BOQ analyses ~= CELERY_WORKER_CONCURRENCY (default 8).
set -euo pipefail
cd "$(dirname "$0")/../backend"
CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-8}"
exec ../.venv/bin/python -m celery -A config worker --loglevel=info --pool=threads --concurrency="$CONCURRENCY"
