"""Celery tasks for BOQ processing."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("boq_ai")


def run_boq_extraction(boq_id: int) -> dict:
    """Extract products and activities from BOQ rows (sync entry point)."""
    from apps.boq.services.boq_analysis_service import BOQAnalysisService

    logger.info("Starting BOQ extraction for id=%s", boq_id)
    return BOQAnalysisService(boq_id).run_extraction()


def run_boq_matching(boq_id: int) -> dict:
    """Match extracted products against the master database (sync entry point)."""
    from apps.boq.services.boq_analysis_service import BOQAnalysisService

    logger.info("Starting BOQ matching for id=%s", boq_id)
    return BOQAnalysisService(boq_id).run_matching()


@shared_task(
    name="boq.process_extraction",
    ignore_result=False,
    max_retries=0,
)
def process_boq_extraction_task(boq_id: int) -> dict:
    """Celery wrapper for BOQ extraction."""
    return run_boq_extraction(boq_id)


@shared_task(
    name="boq.process_matching",
    ignore_result=False,
    max_retries=0,
)
def process_boq_matching_task(boq_id: int) -> dict:
    """Celery wrapper for BOQ matching."""
    return run_boq_matching(boq_id)


# Backward-compatible alias for older queued tasks.
@shared_task(
    name="boq.process_analysis",
    ignore_result=False,
    max_retries=0,
)
def process_boq_analysis_task(boq_id: int) -> dict:
    """Legacy task name — runs extraction only."""
    return run_boq_extraction(boq_id)
