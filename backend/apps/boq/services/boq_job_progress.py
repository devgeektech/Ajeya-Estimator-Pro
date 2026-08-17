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
import threading
import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("boq_ai")

# One progress-echo thread per BOQ in the Django/runserver process so Analyse
# progress is logged on the web terminal (Celery work runs in another process).
_echo_lock = threading.Lock()
_echo_threads: dict[int, threading.Thread] = {}
_ECHO_POLL_SECONDS = 0.8
_ECHO_HEARTBEAT_SECONDS = 10.0
_ECHO_MAX_SECONDS = 3 * 60 * 60

_TTL_SECONDS = 60 * 60
_KEY = "boq_job_progress:{boq_id}"
_EMPTY = {"percent": 0, "label": "", "phase": "", "updated_at": 0.0}
# If progress stops updating while status is PROCESSING/MATCHING, fail the job
# so the expert can click Analyse again. Keep short enough that a killed Celery
# worker does not leave Analyse disabled for many minutes.
_STALE_JOB_SECONDS = 2 * 60
# Terminal 100% while still PROCESSING must age before heal — avoids racing the
# dispatch window (status→PROCESSING before progress reset) and the worker's
# final progress write vs status commit.
_ORPHAN_GRACE_SECONDS = 45


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
    """Store progress 0–100 for status polling (shared across processes).

    Percent is monotonic within a run so the UI never jumps backward (e.g. soft
    creep to 12% then a late 10% write). A low restart (≤8 after ≥15) is allowed
    when Analyse is re-queued.
    """
    try:
        prev_pct = int((_read_file(boq_id).get("percent") or 0))
    except Exception:
        prev_pct = 0
    try:
        next_pct = int(percent)
    except (TypeError, ValueError):
        next_pct = 0
    next_pct = max(0, min(100, next_pct))
    # Explicit restart / queue writes use 1–5%. Block all other decreases so the
    # UI never flickers backward within a run.
    restart = next_pct <= 5
    if not restart and next_pct < prev_pct:
        next_pct = prev_pct

    payload = _normalize(
        {
            "percent": next_pct,
            "label": label,
            "phase": phase or "extract",
            "updated_at": time.time(),
        }
    )
    _write_file(boq_id, payload)
    # Console handler shows this live on the Celery (or sync) terminal.
    logger.info(
        "BOQ Analyse id=%s percent=%s phase=%s label=%s",
        boq_id,
        payload["percent"],
        payload["phase"],
        payload["label"] or "-",
    )
    # Keep worker liveness fresh during long OpenAI batches (Windows threads pool).
    try:
        from celery import current_task

        if current_task is not None:
            from apps.boq.services.celery_worker_heartbeat import (
                touch_celery_worker_heartbeat,
            )

            touch_celery_worker_heartbeat()
    except Exception:
        pass
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


def start_web_progress_echo(boq_id: int, *, boq_name: str = "") -> None:
    """Log shared Analyse progress on the Django/runserver console while work runs.

    Celery updates progress in another process; this watcher mirrors it via
    ``logger.info`` so runserver shows live movement (same console logging as
    the rest of the app — no print statements).
    """
    job_id = int(boq_id)
    name = (boq_name or "").strip()

    def _watch() -> None:
        started = time.time()
        last_marker: tuple[int, str] | None = None
        last_emit = 0.0
        logger.info(
            "BOQ Analyse id=%s%s watching progress on runserver",
            job_id,
            f" name={name}" if name else "",
        )
        while time.time() - started < _ECHO_MAX_SECONDS:
            progress = get_boq_job_progress(job_id)
            percent = int(progress.get("percent") or 0)
            label = str(progress.get("label") or "").strip()
            marker = (percent, label)
            now = time.time()
            changed = marker != last_marker
            heartbeat = (now - last_emit) >= _ECHO_HEARTBEAT_SECONDS
            if changed or heartbeat:
                logger.info(
                    "BOQ Analyse id=%s%s percent=%s label=%s%s",
                    job_id,
                    f" name={name}" if name else "",
                    percent,
                    label or "running",
                    "" if changed else " (still working)",
                )
                last_marker = marker
                last_emit = now
            if percent >= 100:
                break
            # Stop when BOQ left PROCESSING/MATCHING (success or failed).
            try:
                from apps.boq.models import BOQ
                from common.choices import BOQStatus

                status = (
                    BOQ.objects.filter(pk=job_id)
                    .values_list("status", flat=True)
                    .first()
                )
                if status not in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
                    if percent < 100:
                        logger.info(
                            "BOQ Analyse id=%s%s finished status=%s",
                            job_id,
                            f" name={name}" if name else "",
                            status,
                        )
                    break
            except Exception:
                pass
            time.sleep(_ECHO_POLL_SECONDS)
        with _echo_lock:
            current = _echo_threads.get(job_id)
            if current is threading.current_thread():
                _echo_threads.pop(job_id, None)

    with _echo_lock:
        existing = _echo_threads.get(job_id)
        if existing is not None and existing.is_alive():
            return
        thread = threading.Thread(
            target=_watch,
            name=f"boq-progress-echo-{job_id}",
            daemon=True,
        )
        _echo_threads[job_id] = thread
        thread.start()


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
    terminal = _terminal_progress_on_running_job(progress)
    # Require grace so a fresh re-queue (old 100% file) or in-flight complete
    # write is not treated as a dead worker.
    orphaned = (
        terminal
        and age is not None
        and age >= _ORPHAN_GRACE_SECONDS
    )
    stale = age is not None and age >= _STALE_JOB_SECONDS

    if not force and not orphaned and not stale:
        return False
    # Job may have just been queued and not written yet — only force heal when
    # age is unknown (never instant-orphan on a missing timestamp).
    if age is None and not force:
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
