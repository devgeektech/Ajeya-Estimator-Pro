"""Queue or run BOQ extraction via Celery."""
from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings

from apps.boq.models import BOQ
from apps.boq.services.celery_worker_heartbeat import celery_worker_heartbeat_is_fresh
from apps.boq.tasks import (
    process_boq_extraction_task,
    run_boq_extraction,
)
from common.choices import BOQStatus
from config.celery import app as celery_app

logger = logging.getLogger("boq_ai")

_WORKER_REQUIRED_MESSAGE = (
    "Celery worker is not running. Analysis cannot start. "
    "Keep Redis running, then start the worker with "
    ".\\scripts\\run_celery_worker.ps1 (Windows) or ./scripts/run_celery_worker.sh "
    "(Linux) and click Analyse again."
)

_REDIS_REQUIRED_MESSAGE = (
    "Redis is not running. Start Redis, then start the Celery worker "
    "(see docs/OPS.md or run .\\scripts\\run_redis.ps1 on Windows)."
)


@dataclass(frozen=True)
class AnalysisDispatchResult:
    mode: str  # sync | async | failed
    message: str | None = None


def _sync_fallback_enabled() -> bool:
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return True
    if settings.DEBUG:
        return True
    return bool(getattr(settings, "CELERY_SYNC_FALLBACK", False))


def _run_sync_fallback(
    boq_id: int,
    *,
    runner: Callable[[int], dict],
    job_label: str,
    reason: str,
) -> AnalysisDispatchResult | None:
    if not _sync_fallback_enabled():
        return None
    logger.warning(
        "%s Running BOQ %s synchronously for id=%s (sync fallback).",
        reason,
        job_label,
        boq_id,
    )
    runner(boq_id)
    return AnalysisDispatchResult(mode="sync")


def dispatch_boq_extraction(boq_id: int) -> AnalysisDispatchResult:
    """Queue or run AI extraction for one BOQ."""
    return _dispatch_boq_job(
        boq_id,
        task=process_boq_extraction_task,
        runner=run_boq_extraction,
        job_label="extraction",
        pending_status=BOQStatus.PROCESSING,
    )


def _dispatch_boq_job(
    boq_id: int,
    *,
    task,
    runner: Callable[[int], dict],
    job_label: str,
    pending_status: str,
) -> AnalysisDispatchResult:
    if settings.CELERY_TASK_ALWAYS_EAGER:
        runner(boq_id)
        return AnalysisDispatchResult(mode="sync")

    if not broker_is_available():
        fallback = _run_sync_fallback(
            boq_id,
            runner=runner,
            job_label=job_label,
            reason="Redis broker unavailable;",
        )
        if fallback is not None:
            return fallback
        return AnalysisDispatchResult(mode="failed", message=_REDIS_REQUIRED_MESSAGE)

    # Heartbeat is authoritative on Windows (threads pool breaks control inspect).
    # Never queue into Redis when no worker will consume — that freezes Analyse UI.
    if not worker_is_available():
        logger.error(
            "Refusing to queue BOQ %s for id=%s — Celery worker heartbeat missing/stale",
            job_label,
            boq_id,
        )
        fallback = _run_sync_fallback(
            boq_id,
            runner=runner,
            job_label=job_label,
            reason="Celery worker unavailable;",
        )
        if fallback is not None:
            return fallback
        return AnalysisDispatchResult(mode="failed", message=_WORKER_REQUIRED_MESSAGE)

    # Reset progress BEFORE flipping status so a concurrent status poll cannot
    # see PROCESSING + leftover 100% "Analysis complete" and heal the job dead.
    try:
        from apps.boq.services.boq_job_progress import (
            set_boq_job_progress,
            start_web_progress_echo,
        )

        phase = "extract"
        set_boq_job_progress(
            boq_id,
            percent=1,
            label=f"Queued {job_label}…",
            phase=phase,
        )
        boq_name = (
            BOQ.objects.filter(pk=boq_id).values_list("boq_name", flat=True).first()
            or ""
        )
        start_web_progress_echo(boq_id, boq_name=str(boq_name))
    except Exception:
        logger.exception("Failed resetting job progress for boq_id=%s", boq_id)
    BOQ.objects.filter(pk=boq_id).update(status=pending_status)
    try:
        getattr(task, "delay")(boq_id)
        logger.info("Queued BOQ %s for id=%s", job_label, boq_id)
        return AnalysisDispatchResult(mode="async")
    except Exception as exc:
        logger.exception("Failed to queue BOQ %s for id=%s", job_label, boq_id)
        # Roll status back so the UI is not left PROCESSING with no task.
        BOQ.objects.filter(pk=boq_id, status=pending_status).update(
            status=BOQStatus.ANALYSIS_FAILED
        )
        if settings.DEBUG:
            runner(boq_id)
            return AnalysisDispatchResult(mode="sync")
        return AnalysisDispatchResult(
            mode="failed",
            message=f"Could not queue {job_label}: {exc}",
        )


def broker_is_available() -> bool:
    """Return True when the configured Redis broker accepts connections."""
    broker_url = str(settings.CELERY_BROKER_URL or "")
    # Cast keeps pyright on the str overload of urlparse (typeshed dual overload).
    parsed = urlparse(broker_url)  # type: ignore[arg-type]
    if parsed.scheme not in {"redis", "rediss"}:
        return True

    host = str(parsed.hostname or "localhost")
    port = int(parsed.port or 6379)
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def worker_is_available() -> bool:
    """Return True when a Celery worker is alive and can consume Analyse jobs.

    Preference order:
    1. Shared heartbeat file (works with Windows ``threads`` pool)
    2. Celery control ping / stats (works with prefork on Linux)
    """
    if getattr(settings, "CELERY_SKIP_WORKER_CHECK", False):
        return True

    if celery_worker_heartbeat_is_fresh():
        return True

    try:
        replies = celery_app.control.ping(timeout=1.0)
        if replies:
            return True
    except Exception:
        logger.debug("Celery control.ping failed", exc_info=True)

    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        stats = inspector.stats() if inspector else None
        if stats:
            return True
    except Exception:
        logger.debug("Celery worker inspection failed", exc_info=True)

    return False
