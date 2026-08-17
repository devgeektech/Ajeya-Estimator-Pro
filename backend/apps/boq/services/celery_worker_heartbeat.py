"""Shared Celery worker liveness for Analyse dispatch.

Windows ``--pool=threads`` does not support Celery control inspect/ping reliably,
so the web process cannot trust ``inspect.stats()``. The worker writes a heartbeat
file that Analyse checks before queueing jobs.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger("boq_ai")

_DEFAULT_MAX_AGE_SECONDS = 45.0


def _heartbeat_path() -> Path:
    root = Path(settings.MEDIA_ROOT) / "job_progress"
    root.mkdir(parents=True, exist_ok=True)
    return root / "celery_worker_heartbeat.json"


def touch_celery_worker_heartbeat(*, hostname: str = "") -> None:
    """Mark the Celery worker as alive (called from worker signals / tasks)."""
    path = _heartbeat_path()
    payload = {
        "updated_at": time.time(),
        "hostname": str(hostname or "").strip(),
        "pid": os.getpid(),
    }
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        logger.exception("Failed writing Celery worker heartbeat")
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass


def clear_celery_worker_heartbeat() -> None:
    """Remove the heartbeat so the web process stops treating the worker as live."""
    path = _heartbeat_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        logger.warning("Failed clearing Celery worker heartbeat", exc_info=True)


def read_celery_worker_heartbeat() -> dict[str, Any]:
    path = _heartbeat_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    try:
        updated_at = float(data.get("updated_at") or 0)
    except (TypeError, ValueError):
        updated_at = 0.0
    return {
        "updated_at": updated_at,
        "hostname": str(data.get("hostname") or ""),
        "pid": data.get("pid"),
        "age_seconds": max(0.0, time.time() - updated_at) if updated_at else None,
    }


def celery_worker_heartbeat_is_fresh(*, max_age_seconds: float | None = None) -> bool:
    """True when a worker touched the heartbeat within ``max_age_seconds``."""
    max_age = float(
        max_age_seconds
        if max_age_seconds is not None
        else getattr(settings, "CELERY_WORKER_HEARTBEAT_MAX_AGE", _DEFAULT_MAX_AGE_SECONDS)
    )
    payload = read_celery_worker_heartbeat()
    age = payload.get("age_seconds")
    if age is None:
        return False
    return float(age) <= max_age
