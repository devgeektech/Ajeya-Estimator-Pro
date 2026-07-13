#!/usr/bin/env bash
# Start Celery worker for BOQ analysis.
# Requires Redis at redis://localhost:6379/0
set -euo pipefail
cd "$(dirname "$0")/../backend"
exec ../.venv/bin/python -m celery -A config worker --loglevel=info --pool=solo
