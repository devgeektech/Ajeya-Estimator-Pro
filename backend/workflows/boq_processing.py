"""BOQ processing workflow.

Drives a BOQ run through its processing stages and keeps the ProcessingJob
progress + status in sync (docs/ARCHITECTURE.md - BOQ Processing Architecture).
Invoked from a Celery task so views never block (docs/AGENTS.md - Background
Jobs).

Stage pipeline (fixed order):

    AI analysis → product matching → costing → confidence scoring

Each stage delegates to its dedicated service module:
- ``ai_analysis``:  Product + activity extraction via AIService (Sprints 8-9).
                   Skipped gracefully when AI is disabled (placeholder key).
- ``matching``:    Exact/alias/vector matching + vendor selection (Sprints 10-12).
- ``costing``:     Material + labour + commercial cost breakdown (Sprints 13-15).
- ``confidence``:  Factor-weighted scoring + colour bands (Sprint 11).

All stages are fully implemented and deterministic. AI stages degrade gracefully
when no real OPENAI_API_KEY is configured.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from common.choices import BOQStatus, RunStatus
from common.exceptions import ProcessingError

logger = logging.getLogger("boq_ai")

# (progress %, label, stage key). Stage keys map to future service hooks.
STAGES = [
    (30, "Analyzing descriptions", "ai_analysis"),
    (60, "Matching products", "matching"),
    (85, "Calculating costs", "costing"),
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
    - matching:    ProductMatchingService (exact/alias/vector) + VendorSelectionService
                   (make-list aware) — runs with or without AI (Sprints 10-12).
    - costing:     Full per-item cost breakdown: material, labour, accessories,
                   transportation, overhead, profit (Sprints 13-15).
    - confidence:  Factor-weighted scoring, colour bands, match explanations (Sprint 11).
    """
    if stage_key == "ai_analysis":
        from ai.service import AIService

        if AIService.is_enabled():
            from ai.extractors.analyzer import analyze_run

            analyze_run(run)
        else:
            logger.info("Run %s: AI disabled (placeholder key) - skipping AI analysis", run.pk)
        return

    if stage_key == "matching":
        from apps.matching.services.matching_service import ProductMatchingService
        from apps.matching.services.vendor_selection import VendorSelectionService

        ProductMatchingService().match_run(run, created_by=run.boq.user)
        VendorSelectionService().select_run(run)
        return

    if stage_key == "costing":
        from apps.costing.services.cost_service import CostCalculationService

        CostCalculationService().calculate_run(run)
        return

    if stage_key == "confidence":
        from apps.matching.services.confidence import ConfidenceService

        ConfidenceService().score_run(run)
        return

    logger.info("Run %s: stage '%s' pending implementation", run.pk, stage_key)


def process_boq_run(boq_run_id: int) -> int:
    """Process a BOQ run end-to-end. Returns the run id."""
    from apps.boq.models import BOQRun
    from apps.processing.models import ProcessingJob

    run = BOQRun.objects.select_related("boq").get(pk=boq_run_id)
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
        boq.status = BOQStatus.COMPLETED
        boq.save(update_fields=["status"])
        _update_job(job, progress=100, status=RunStatus.COMPLETED, message="Completed")
        logger.info("Run %s completed", run.pk)

        from apps.notifications.services import notify

        notify(
            boq.user,
            "Processing complete",
            f"'{boq.boq_name}' (run {run.run_number}) is ready for review.",
        )
        return run.pk

    except Exception as exc:  # noqa: BLE001 - record failure then re-raise
        logger.exception("Run %s failed", boq_run_id)
        run.status = RunStatus.FAILED
        run.save(update_fields=["status"])
        _update_job(job, status=RunStatus.FAILED, message=f"Failed: {exc}")

        from apps.notifications.services import notify

        notify(boq.user, "Processing failed", f"'{boq.boq_name}' failed: {exc}")
        raise ProcessingError(str(exc)) from exc
