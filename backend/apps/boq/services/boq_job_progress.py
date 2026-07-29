"""Job progress for Analyse / Match polling UI.

Progress must be visible to both the Celery worker and the web process.
Django's default LocMem cache is per-process, so workers updating LocMem never
reach status polling (UI stuck at the 3% fallback). We write a shared media
file and also mirror into cache when available.

Files are keyed by ``boq_id`` so concurrent jobs never share progress state.
Writes are atomic (temp file + replace) to avoid empty-file races while the
status endpoint polls.

The shared progress **file** is the source of truth across processes. Cache is
only a fallback when the file is missing — never prefer a higher cached percent
over a newer lower file value (that caused re-Analyse to show 99%).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("boq_ai")

_TTL_SECONDS = 60 * 60
_KEY = "boq_job_progress:{boq_id}"
_EMPTY = {"percent": 0, "label": "", "phase": "", "updated_at": 0.0}
# If progress stops updating while status is PROCESSING/MATCHING, fail the job
# so the expert can click Analyse again.
_STALE_JOB_SECONDS = 5 * 60


def _key(boq_id: int) -> str:
    return _KEY.format(boq_id=int(boq_id))


def _progress_path(boq_id: int) -> Path:
    root = Path(settings.MEDIA_ROOT) / "job_progress"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{int(boq_id)}.json"


def _normalize(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return dict(_EMPTY)
    try:
        percent = int(payload.get("percent") or 0)
    except (TypeError, ValueError):
        percent = 0
    try:
        updated_at = float(payload.get("updated_at") or 0)
    except (TypeError, ValueError):
        updated_at = 0.0
    return {
        "percent": max(0, min(100, percent)),
        "label": str(payload.get("label") or "").strip(),
        "phase": str(payload.get("phase") or "").strip(),
        "updated_at": max(0.0, updated_at),
    }


def _read_file(boq_id: int) -> dict[str, Any]:
    path = _progress_path(boq_id)
    if not path.is_file():
        return dict(_EMPTY)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Failed reading job progress file for boq_id=%s", boq_id, exc_info=True)
        return dict(_EMPTY)

    # Empty / partial reads happen when a writer replaces the file mid-poll.
    if not text.strip():
        return dict(_EMPTY)
    try:
        return _normalize(json.loads(text))
    except json.JSONDecodeError:
        logger.warning(
            "Ignoring incomplete job progress JSON for boq_id=%s (concurrent write)",
            boq_id,
        )
        return dict(_EMPTY)
    except Exception:
        logger.warning("Failed parsing job progress file for boq_id=%s", boq_id, exc_info=True)
        return dict(_EMPTY)


def _write_file(boq_id: int, payload: dict[str, Any]) -> None:
    path = _progress_path(boq_id)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        logger.exception("Failed writing job progress file for boq_id=%s", boq_id)
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass


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
            "updated_at": time.time(),
        }
    )
    _write_file(boq_id, payload)
    try:
        cache.set(_key(boq_id), payload, timeout=_TTL_SECONDS)
    except Exception:
        logger.exception("Failed caching job progress for boq_id=%s", boq_id)


def get_boq_job_progress(boq_id: int) -> dict[str, Any]:
    """Return ``{percent, label, phase, updated_at}`` from the shared file."""
    file_payload = _read_file(boq_id)
    file_pct = int(file_payload.get("percent") or 0)
    if file_pct > 0 or file_payload.get("label") or file_payload.get("updated_at"):
        # Keep web-process LocMem aligned with the shared file so a prior 100%
        # cache entry cannot win over a fresh re-queue at 1%.
        try:
            cache.set(_key(boq_id), file_payload, timeout=_TTL_SECONDS)
        except Exception:
            pass
        return file_payload

    try:
        return _normalize(cache.get(_key(boq_id)) or {})
    except Exception:
        return dict(_EMPTY)


def progress_age_seconds(boq_id: int) -> float | None:
    """Seconds since progress was last written, or None if missing."""
    payload = _read_file(boq_id)
    updated_at = float(payload.get("updated_at") or 0)
    if updated_at > 0:
        return max(0.0, time.time() - updated_at)

    path = _progress_path(boq_id)
    try:
        if not path.is_file():
            return None
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


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


def _terminal_progress_on_running_job(progress: dict[str, Any]) -> bool:
    """True when progress looks finished/failed but BOQ status is still running."""
    percent = int(progress.get("percent") or 0)
    label = str(progress.get("label") or "").lower()
    if percent < 100:
        return False
    markers = ("complete", "failed", "stalled", "error", "timed out", "timeout")
    return any(marker in label for marker in markers)


def fail_stale_or_orphaned_boq_job(
    boq,
    *,
    reason: str | None = None,
    force: bool = False,
) -> bool:
    """
    Mark a stuck PROCESSING/MATCHING BOQ so Analyse can be started again.

    Triggers when:
    - progress has not updated for ``_STALE_JOB_SECONDS``, or
    - progress already shows 100% complete/failed/stalled while status is still
      running (orphaned after worker death), or
    - ``force=True`` (Celery task hard-failure / timeout).

    Returns True when status was changed.
    """
    from apps.boq.models import BOQ
    from common.choices import BOQStatus

    if boq.status not in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
        return False

    progress = get_boq_job_progress(boq.pk)
    age = progress_age_seconds(boq.pk)
    orphaned = _terminal_progress_on_running_job(progress)
    stale = age is not None and age >= _STALE_JOB_SECONDS

    if not force and not orphaned and not stale:
        return False
    # Job may have just been queued and not written yet — only force/orphan heal
    # when age is unknown.
    if age is None and not force and not orphaned:
        return False

    previous = boq.status
    has_rows = bool((getattr(boq, "analysis_data", None) or {}).get("rows"))
    # MATCHING stall: extraction already saved — return to EXTRACTED for retry.
    # PROCESSING stall: always ANALYSIS_FAILED so Analyse can be clicked again
    # (old rows may still be present during re-analyse and must not look successful).
    if previous == BOQStatus.MATCHING and has_rows:
        next_status = BOQStatus.EXTRACTED
        label = reason or "Matching stalled - open Analysis and retry when ready"
        phase = "match"
    else:
        next_status = BOQStatus.ANALYSIS_FAILED
        label = reason or "Analysis stalled - click Analyse BOQ to retry"
        phase = "extract" if previous == BOQStatus.PROCESSING else "match"

    updated = BOQ.objects.filter(pk=boq.pk, status=previous).update(status=next_status)
    if not updated:
        return False
    boq.status = next_status
    set_boq_job_progress(boq.pk, percent=100, label=label, phase=phase)
    logger.warning(
        "Failed stuck BOQ job id=%s previous=%s next=%s age=%s orphaned=%s force=%s reason=%s",
        boq.pk,
        previous,
        next_status,
        f"{age:.0f}s" if age is not None else "unknown",
        orphaned,
        force,
        label,
    )
    try:
        from apps.notifications.services import notify

        notify(
            getattr(boq, "user", None),
            "BOQ analysis stalled",
            f"BOQ '{getattr(boq, 'boq_name', boq.pk)}' stopped. {label}",
        )
    except Exception:
        logger.exception("Failed notifying stuck BOQ heal for id=%s", boq.pk)
    return True


def heal_stale_running_boq(boq) -> bool:
    """Backward-compatible alias for status-poll stuck-job recovery."""
    return fail_stale_or_orphaned_boq_job(boq)
