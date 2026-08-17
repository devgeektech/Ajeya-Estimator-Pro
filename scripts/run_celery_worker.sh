#!/usr/bin/env bash
# Start Celery worker for BOQ analysis with auto-restart.
# Requires Redis at redis://localhost:6379/0
# Concurrent BOQ analyses ~= CELERY_WORKER_CONCURRENCY (default 8).
set -uo pipefail
cd "$(dirname "$0")/../backend"
CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-8}"
POOL="${CELERY_WORKER_POOL:-threads}"
RESTART_DELAY="${CELERY_WORKER_RESTART_DELAY:-3}"

# Stop leftover workers from earlier shells so nodenames do not collide.
pkill -f 'celery -A config worker' 2>/dev/null || true
sleep 1

echo "BOQ_AI Celery worker (pool=$POOL concurrency=$CONCURRENCY)"
echo "Auto-restart enabled. Ctrl+C twice to stop."
echo "Watch THIS terminal for BOQ Analyse log lines while analysing."
echo "Run only ONE Celery terminal — extras cause DuplicateNodenameWarning."

export PYTHONUNBUFFERED=1

while true; do
  # Unique nodename per process (avoids DuplicateNodenameWarning).
  NODE_NAME="boq-$$@$(hostname -s 2>/dev/null || hostname)"
  echo "[$(date +%H:%M:%S)] Starting Celery worker as $NODE_NAME..."
  ../.venv/bin/python -m celery -A config worker \
    --loglevel=info \
    --pool="$POOL" \
    --concurrency="$CONCURRENCY" \
    --hostname="$NODE_NAME" || true
  code=$?
  echo "[$(date +%H:%M:%S)] Celery exited (code=$code). Restarting in ${RESTART_DELAY}s..."
  sleep "$RESTART_DELAY"
done
