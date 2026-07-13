"""Queue or run BOQ extraction and matching via Celery."""
from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings

from apps.boq.models import BOQ
from apps.boq.tasks import (
    process_boq_extraction_task,
    process_boq_matching_task,
    run_boq_extraction,
    run_boq_matching,
)
from common.choices import BOQStatus
from config.celery import app as celery_app

logger = logging.getLogger("boq_ai")


@dataclass(frozen=True)
class AnalysisDispatchResult:
    mode: str  # sync | async | failed
    message: str | None = None


def dispatch_boq_extraction(boq_id: int) -> AnalysisDispatchResult:
    """Queue or run AI extraction for one BOQ."""
    return _dispatch_boq_job(
        boq_id,
        task=process_boq_extraction_task,
        runner=run_boq_extraction,
        job_label="extraction",
        pending_status=BOQStatus.PROCESSING,
    )


def dispatch_boq_matching(boq_id: int) -> AnalysisDispatchResult:
    """Queue or run database matching for one BOQ."""
    return _dispatch_boq_job(
        boq_id,
        task=process_boq_matching_task,
        runner=run_boq_matching,
        job_label="matching",
        pending_status=BOQStatus.MATCHING,
    )


def dispatch_boq_analysis(boq_id: int) -> AnalysisDispatchResult:
    """Backward-compatible alias for extraction dispatch."""
    return dispatch_boq_extraction(boq_id)


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
        if settings.DEBUG:
            logger.warning("Redis unavailable in DEBUG; running BOQ %s synchronously", job_label)
            runner(boq_id)
            return AnalysisDispatchResult(mode="sync")
        return AnalysisDispatchResult(
            mode="failed",
            message=(
                "Redis is not running. Start Redis, then start the Celery worker "
                "(see README / docs/OPS.md)."
            ),
        )

    if not worker_is_available():
        if settings.DEBUG:
            logger.warning(
                "No Celery worker detected in DEBUG; running BOQ %s synchronously",
                job_label,
            )
            runner(boq_id)
            return AnalysisDispatchResult(mode="sync")
        return AnalysisDispatchResult(
            mode="failed",
            message=(
                "No Celery worker is running. Start the worker in a separate terminal "
                "(see README / docs/OPS.md)."
            ),
        )

    BOQ.objects.filter(pk=boq_id).update(status=pending_status)
    try:
        getattr(task, "delay")(boq_id)
        logger.info("Queued BOQ %s for id=%s", job_label, boq_id)
        return AnalysisDispatchResult(mode="async")
    except Exception as exc:
        logger.exception("Failed to queue BOQ %s for id=%s", job_label, boq_id)
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
    parsed = urlparse(broker_url)
    if parsed.scheme not in {"redis", "rediss"}:
        return True

    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def worker_is_available() -> bool:
    """Return True when at least one Celery worker responds to ping."""
    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        stats = inspector.stats() if inspector else None
        return bool(stats)
    except Exception:
        logger.exception("Celery worker inspection failed")
        return False
