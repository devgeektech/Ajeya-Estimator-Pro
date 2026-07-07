"""Processing job orchestration.

Creates/queues processing jobs and dispatches the background task. Reprocessing
creates a NEW run, preserving prior runs and their results
(docs/PRD.md - Historical Processing, docs/AGENTS.md - BOQ Rules).
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.make_list.models import MakeListEntry
from apps.processing.models import ProcessingJob
from common.choices import BOQStatus, RunStatus
from tasks.process_boq import process_boq_task

logger = logging.getLogger("boq_ai")

# A run that is already active should not be restarted.
ACTIVE_RUN_STATES = {RunStatus.QUEUED, RunStatus.PROCESSING}


class ProcessingJobService:
    def __init__(self, boq: BOQ):
        self.boq = boq

    def start(self) -> ProcessingJob:
        """Queue processing for the BOQ and dispatch the background task."""
        with transaction.atomic():  # type: ignore
            run = self._resolve_target_run()
            job, _ = ProcessingJob.objects.get_or_create(boq_run=run)
            job.status = RunStatus.QUEUED
            job.progress = 0
            job.message = "Queued"
            job.save(update_fields=["status", "progress", "message", "updated_at"])

            run.status = RunStatus.QUEUED
            run.started_at = None
            run.completed_at = None
            run.save(update_fields=["status", "started_at", "completed_at"])

            self.boq.status = BOQStatus.PROCESSING
            self.boq.save(update_fields=["status"])

            transaction.on_commit(lambda: self._dispatch(run.pk))
            logger.info("Queued processing for BOQ %s (run %s)", self.boq.pk, run.run_number)
            return job

    def _resolve_target_run(self) -> BOQRun:
        latest = self.boq.runs.order_by("-run_number").first()
        if latest is None:
            return BOQRun.objects.create(
                boq=self.boq, run_number=1, status=RunStatus.QUEUED
            )
        if latest.status in ACTIVE_RUN_STATES:
            return latest
        # Previous run finished (completed/failed) -> reprocess in a new run.
        return self._clone_run(latest)

    def _clone_run(self, source: BOQRun) -> BOQRun:
        new_run = BOQRun.objects.create(
            boq=self.boq,
            run_number=source.run_number + 1,
            status=RunStatus.QUEUED,
            original_headers=source.original_headers,
        )
        items = [
            BOQItem(
                boq_run=new_run,
                row_number=item.row_number,
                description=item.description,
                quantity=item.quantity,
                unit=item.unit,
                original_data=item.original_data,
                row_json=item.row_json,
            )
            for item in source.items.all()
        ]
        if items:
            BOQItem.objects.bulk_create(items, batch_size=500)
        makes = [
            MakeListEntry(boq_run=new_run, make=m.make, category=m.category)
            for m in source.make_list_entries.all()
        ]
        if makes:
            MakeListEntry.objects.bulk_create(makes, batch_size=500)
        logger.info("Cloned run %s -> %s for reprocessing", source.run_number, new_run.run_number)
        return new_run

    @staticmethod
    def _dispatch(run_id: int) -> None:
        process_boq_task.delay(run_id)  # type: ignore
