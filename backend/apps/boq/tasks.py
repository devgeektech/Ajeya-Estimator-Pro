"""Celery tasks for BOQ processing."""
from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

logger = logging.getLogger("boq_ai")

# Soft limit leaves room for cleanup before hard kill (settings CELERY_TASK_TIME_LIMIT).
_SOFT_TIME_LIMIT_SECONDS = 60 * 25


def run_boq_extraction(boq_id: int) -> dict:
    """Extract products from BOQ rows (sync entry point)."""
    from apps.boq.services.boq_analysis_service import BOQAnalysisService
    from apps.boq.services.celery_worker_heartbeat import touch_celery_worker_heartbeat

    touch_celery_worker_heartbeat()
    logger.info("Starting BOQ extraction for id=%s", boq_id)
    return BOQAnalysisService(boq_id).run_extraction()


def _fail_boq_job(boq_id: int, *, reason: str) -> None:
    """Unblock the UI when a Celery task dies without a clean service failure path."""
    try:
        from apps.boq.models import BOQ
        from apps.boq.services.boq_job_progress import fail_stale_or_orphaned_boq_job
        from utils.json_safe import json_safe
        from utils.timestamps import now_local_iso

        boq = BOQ.objects.filter(pk=boq_id).only(
            "pk", "status", "analysis_data", "boq_name", "user_id"
        ).first()
        if boq is None:
            return
        fail_stale_or_orphaned_boq_job(boq, reason=reason, force=True)
        # Keep a durable copy for the Analysis banner after reload.
        from common.choices import BOQStatus

        boq.refresh_from_db(fields=["status", "analysis_data"])
        if boq.status == BOQStatus.ANALYSIS_FAILED:
            data = dict(boq.analysis_data or {})
            # Prefer an existing specific message from the service path.
            if not str(data.get("last_error") or "").strip():
                data["last_error"] = reason
                data["last_error_at"] = now_local_iso()
                BOQ.objects.filter(pk=boq.pk).update(analysis_data=json_safe(data))
            elif reason and "credits" in reason.casefold():
                data["last_error"] = reason
                data["last_error_at"] = now_local_iso()
                BOQ.objects.filter(pk=boq.pk).update(analysis_data=json_safe(data))
    except Exception:
        logger.exception("Failed to mark BOQ job failed for id=%s", boq_id)


@shared_task(
    name="boq.process_extraction",
    ignore_result=False,
    max_retries=0,
    soft_time_limit=_SOFT_TIME_LIMIT_SECONDS,
)
def process_boq_extraction_task(boq_id: int) -> dict:
    """Celery wrapper for BOQ extraction."""
    try:
        return run_boq_extraction(boq_id)
    except SoftTimeLimitExceeded:
        logger.error("BOQ extraction timed out for id=%s", boq_id)
        _fail_boq_job(
            boq_id,
            reason="Analysis timed out - click Analyse BOQ to retry",
        )
        raise
    except Exception as exc:
        from ai.errors import format_ai_error_message

        logger.exception("BOQ extraction task crashed for id=%s", boq_id)
        _fail_boq_job(
            boq_id,
            reason=format_ai_error_message(exc),
        )
        raise


# Backward-compatible alias for older queued tasks.
@shared_task(
    name="boq.process_analysis",
    ignore_result=False,
    max_retries=0,
    soft_time_limit=_SOFT_TIME_LIMIT_SECONDS,
)
def process_boq_analysis_task(boq_id: int) -> dict:
    """Legacy task name — runs extraction only."""
    try:
        return run_boq_extraction(boq_id)
    except SoftTimeLimitExceeded:
        logger.error("BOQ analysis timed out for id=%s", boq_id)
        _fail_boq_job(
            boq_id,
            reason="Analysis timed out - click Analyse BOQ to retry",
        )
        raise
    except Exception as exc:
        from ai.errors import format_ai_error_message

        logger.exception("BOQ analysis task crashed for id=%s", boq_id)
        _fail_boq_job(
            boq_id,
            reason=format_ai_error_message(exc),
        )
        raise
