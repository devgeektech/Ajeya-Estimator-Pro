"""BOQ creation service.

Creates a BOQ, its first processing run, and captures the original BOQ rows
and approved makes. Each BOQ is owned by the uploading user
(docs/PRD.md - BOQ Ownership). Historical data is preserved: reprocessing
creates a new run rather than overwriting (docs/AGENTS.md - BOQ Rules).
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.make_list.models import MakeListEntry
from common.choices import BOQStatus, RunStatus
from apps.audit.services import record

from .parser import parse_boq_workbook, parse_make_list

logger = logging.getLogger("boq_ai")


class BOQCreationService:
    def __init__(self, user, boq_name, uploaded_file, make_list_file=None):
        self.user = user
        self.boq_name = boq_name
        self.uploaded_file = uploaded_file
        self.make_list_file = make_list_file

    @transaction.atomic
    def run(self) -> BOQ:
        boq = BOQ.objects.create(
            user=self.user,
            boq_name=self.boq_name,
            status=BOQStatus.UPLOADED,
            uploaded_file=self.uploaded_file,
            make_list_file=self.make_list_file,
        )
        run = BOQRun.objects.create(boq=boq, run_number=1, status=RunStatus.QUEUED)

        self._capture_items(run, boq)
        self._capture_make_list(run, boq)

        logger.info("BOQ created: '%s' (id=%s) by %s", boq.boq_name, boq.pk, self.user.email)
        record(self.user, "Uploaded BOQ", "BOQ", boq.boq_name)
        return boq

    def _capture_items(self, run: BOQRun, boq: BOQ) -> None:
        try:
            headers, items = parse_boq_workbook(boq.uploaded_file.path)
        except Exception:  # noqa: BLE001 - parsing is best-effort at upload
            logger.exception("Failed to parse BOQ items for BOQ %s", boq.pk)
            return
        run.original_headers = headers
        run.save(update_fields=["original_headers"])
        objects = [BOQItem(boq_run=run, **item) for item in items]
        if objects:
            BOQItem.objects.bulk_create(objects, batch_size=500)
        logger.info("Parsed %s BOQ items for BOQ %s", len(objects), boq.pk)

    def _capture_make_list(self, run: BOQRun, boq: BOQ) -> None:
        if not boq.make_list_file:
            return
        try:
            entries = parse_make_list(boq.make_list_file.path)
        except Exception:  # noqa: BLE001 - best-effort
            logger.exception("Failed to parse make list for BOQ %s", boq.pk)
            return
        objects = [MakeListEntry(boq_run=run, **entry) for entry in entries]
        if objects:
            MakeListEntry.objects.bulk_create(objects, batch_size=500)
        logger.info("Parsed %s make-list entries for BOQ %s", len(objects), boq.pk)
