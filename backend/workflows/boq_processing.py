"""BOQ processing workflow.

Drives a BOQ run through its processing stages and keeps the ProcessingJob
progress + status in sync (docs/ARCHITECTURE.md - BOQ Processing Architecture).
Invoked from a Celery task so views never block (docs/AGENTS.md - Background
Jobs).

Stage pipeline (fixed order):

    AI analysis → product matching → rate/labour retrieval → confidence scoring

Each stage delegates to its dedicated service module:
- ``ai_analysis``:  Product + activity extraction via AIService (Sprints 8-9).
                   Skipped gracefully when AI is disabled (placeholder key).
- ``matching``:    Exact/alias/vector matching with lowest final-amount selection.
- ``rate_detail``: Retrieve selected Rate_Master/Labour_Master values.
- ``confidence``:  Factor-weighted scoring + colour bands (Sprint 11).

All stages are fully implemented and deterministic. AI stages degrade gracefully
when no real OPENAI_API_KEY is configured.
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.utils import timezone

from ai.extractors.analyzer import analyze_run
from ai.service import AIService
from apps.boq.models import BOQRun
from apps.costing.services.rate_detail import RateDetailRetrievalService
from apps.matching.services.confidence import ConfidenceService
from apps.matching.services.matching_service import ProductMatchingService
from apps.notifications.services import notify
from apps.processing.models import ProcessingJob
from common.choices import BOQStatus, RunStatus
from common.exceptions import ProcessingError

logger = logging.getLogger("boq_ai")

# (progress %, label, stage key). Stage keys map to the implemented service calls below.
STAGES = [
    (30, "Analyzing descriptions", "ai_analysis"),
    (60, "Matching products", "matching"),
    (85, "Retrieving rate and labour details", "rate_detail"),
    (95, "Scoring confidence", "confidence"),
]


def _update_job(job, *, progress=None, status=None, message=None) -> None:
    fields = []
    if progress is not None:
        job.progress = progress
        fields.append("progress")
    if status is not None:
        job.status = status
        fields.append("status")
    if message is not None:
        job.message = message
        fields.append("message")
    if fields:
        job.save(update_fields=fields + ["updated_at"])


def _run_stage(run, stage_key: str) -> None:
    """Execute a single pipeline stage.

    All four stages are fully implemented:
    - ai_analysis: product + activity extraction via AIService (Sprints 8-9);
                   skipped gracefully when OPENAI_API_KEY is a placeholder.
    - matching:    ProductMatchingService (exact/alias/vector), selecting the
                   lowest Final_Amount_(Excl GST) RateMaster row among matches.
    - rate_detail: Selected Rate_Master and linked Labour_Master value retrieval.
    - confidence:  Factor-weighted scoring, colour bands, match explanations (Sprint 11).
    """
    if stage_key == "ai_analysis":
        if AIService.is_enabled():
            analyze_run(run)
        else:
            logger.info("Run %s: AI disabled (placeholder key) - skipping AI analysis", run.pk)
        return

    if stage_key == "matching":
        ProductMatchingService().match_run(run, created_by=run.boq.user)
        return

    if stage_key == "rate_detail":
        RateDetailRetrievalService().retrieve_run(run)
        return

    if stage_key == "confidence":
        ConfidenceService().score_run(run)
        return

    raise ProcessingError(f"Unknown processing stage: {stage_key}")


def process_boq_run(boq_run_id: int) -> int | None:
    """Process a BOQ run end-to-end. Returns the run id when processed."""
    try:
        run = BOQRun.objects.select_related("boq").get(pk=boq_run_id)
    except BOQRun.DoesNotExist:
        logger.warning("Skipping BOQ processing task: run %s no longer exists", boq_run_id)
        return None

    job, _ = ProcessingJob.objects.get_or_create(boq_run=run)
    boq = run.boq

    try:
        run.status = RunStatus.PROCESSING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])
        boq.status = BOQStatus.PROCESSING
        boq.save(update_fields=["status"])
        _update_job(job, progress=5, status=RunStatus.PROCESSING, message="Processing started")

        for progress, label, stage_key in STAGES:
            _run_stage(run, stage_key)
            _update_job(job, progress=progress, message=label)

        run.status = RunStatus.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        boq.status = BOQStatus.UNDER_REVIEW
        boq.save(update_fields=["status"])
        _update_job(job, progress=100, status=RunStatus.COMPLETED, message="Completed")
        logger.info("Run %s completed", run.pk)

        notify(
            boq.user,
            "Processing complete",
            f"'{boq.boq_name}' (run {run.run_number}) is ready for review.",
        )
        User = get_user_model()
        for admin in User.objects.filter(role="SUPERADMIN").exclude(pk=boq.user.pk):
            notify(
                admin,
                "Processing complete",
                f"'{boq.boq_name}' (uploaded by {boq.user.full_name}) is ready for review.",
            )

        return run.pk

    except Exception as exc:  # noqa: BLE001 - record failure then re-raise
        logger.exception("Run %s failed", boq_run_id)
        run.status = RunStatus.FAILED
        run.save(update_fields=["status"])
        _update_job(job, status=RunStatus.FAILED, message=f"Failed: {exc}")

        notify(boq.user, "Processing failed", f"'{boq.boq_name}' failed: {exc}")
        User = get_user_model()
        for admin in User.objects.filter(role="SUPERADMIN").exclude(pk=boq.user.pk):
            notify(admin, "Processing failed", f"'{boq.boq_name}' failed: {exc}")

        raise ProcessingError(str(exc)) from exc
