"""Lightweight job progress for Analyse / Match polling UI."""
from __future__ import annotations

from typing import Any

from django.core.cache import cache

_TTL_SECONDS = 60 * 60
_KEY = "boq_job_progress:{boq_id}"


def _key(boq_id: int) -> str:
    return _KEY.format(boq_id=int(boq_id))


def set_boq_job_progress(
    boq_id: int,
    *,
    percent: int,
    label: str = "",
    phase: str = "extract",
) -> None:
    """Store progress 0–100 for status polling."""
    clamped = max(0, min(100, int(percent)))
    cache.set(
        _key(boq_id),
        {
            "percent": clamped,
            "label": str(label or "").strip(),
            "phase": str(phase or "extract").strip(),
        },
        timeout=_TTL_SECONDS,
    )


def get_boq_job_progress(boq_id: int) -> dict[str, Any]:
    """Return ``{percent, label, phase}`` or empty defaults."""
    payload = cache.get(_key(boq_id)) or {}
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


def clear_boq_job_progress(boq_id: int) -> None:
    cache.delete(_key(boq_id))
