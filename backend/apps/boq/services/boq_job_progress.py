"""Job progress for Analyse / Match polling UI.

Progress must be visible to both the Celery worker and the web process.
Django's default LocMem cache is per-process, so workers updating LocMem never
reach status polling (UI stuck at the 3% fallback). We write a shared media
file and also mirror into cache when available.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("boq_ai")

_TTL_SECONDS = 60 * 60
_KEY = "boq_job_progress:{boq_id}"


def _key(boq_id: int) -> str:
    return _KEY.format(boq_id=int(boq_id))


def _progress_path(boq_id: int) -> Path:
    root = Path(settings.MEDIA_ROOT) / "job_progress"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{int(boq_id)}.json"


def _normalize(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"percent": 0, "label": "", "phase": ""}
    try:
        percent = int(payload.get("percent") or 0)
    except (TypeError, ValueError):
        percent = 0
    return {
        "percent": max(0, min(100, percent)),
        "label": str(payload.get("label") or "").strip(),
        "phase": str(payload.get("phase") or "").strip(),
    }


def _read_file(boq_id: int) -> dict[str, Any]:
    path = _progress_path(boq_id)
    if not path.is_file():
        return {"percent": 0, "label": "", "phase": ""}
    try:
        return _normalize(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        logger.exception("Failed reading job progress file for boq_id=%s", boq_id)
        return {"percent": 0, "label": "", "phase": ""}


def _write_file(boq_id: int, payload: dict[str, Any]) -> None:
    path = _progress_path(boq_id)
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Failed writing job progress file for boq_id=%s", boq_id)


def set_boq_job_progress(
    boq_id: int,
    *,
    percent: int,
    label: str = "",
    phase: str = "extract",
) -> None:
    """Store progress 0–100 for status polling (shared across processes)."""
    payload = _normalize(
        {
            "percent": percent,
            "label": label,
            "phase": phase or "extract",
        }
    )
    _write_file(boq_id, payload)
    try:
        cache.set(_key(boq_id), payload, timeout=_TTL_SECONDS)
    except Exception:
        logger.exception("Failed caching job progress for boq_id=%s", boq_id)


def get_boq_job_progress(boq_id: int) -> dict[str, Any]:
    """Return ``{percent, label, phase}`` from shared file and/or cache."""
    file_payload = _read_file(boq_id)
    try:
        cached = _normalize(cache.get(_key(boq_id)) or {})
    except Exception:
        cached = {"percent": 0, "label": "", "phase": ""}

    file_pct = int(file_payload.get("percent") or 0)
    cache_pct = int(cached.get("percent") or 0)
    if cache_pct > file_pct:
        return cached
    if file_pct > 0 or file_payload.get("label"):
        return file_payload
    return cached


def clear_boq_job_progress(boq_id: int) -> None:
    path = _progress_path(boq_id)
    try:
        if path.is_file():
            path.unlink()
    except Exception:
        logger.exception("Failed deleting job progress file for boq_id=%s", boq_id)
    try:
        cache.delete(_key(boq_id))
    except Exception:
        logger.exception("Failed deleting job progress cache for boq_id=%s", boq_id)
