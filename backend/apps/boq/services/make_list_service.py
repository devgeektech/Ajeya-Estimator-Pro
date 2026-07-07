"""Make-list upload service for a single BOQ.

Make lists are scoped to a BOQ run through MakeListEntry.boq_run. Updating a
make list here replaces entries only on the target BOQ's latest run.
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.boq.models import BOQ
from apps.make_list.models import MakeListEntry
from common.choices import RunStatus
from common.exceptions import ValidationError

from .parser import parse_make_list

logger = logging.getLogger("boq_ai")


class BOQMakeListUploadService:
    """Attach a make-list file and parsed entries to one BOQ's latest run."""

    def __init__(self, boq: BOQ, make_list_file):
        self.boq = boq
        self.make_list_file = make_list_file

    @transaction.atomic
    def run(self) -> int:
        run = self.boq.runs.order_by("-run_number").first()
        if run is None:
            raise ValidationError("This BOQ has no processing run to attach makes to.")
        if run.status == RunStatus.PROCESSING:
            raise ValidationError("Cannot update the make list while this BOQ is processing.")

        self.boq.make_list_file = self.make_list_file
        self.boq.save(update_fields=["make_list_file"])

        entries = parse_make_list(self.boq.make_list_file.path)
        if not entries:
            raise ValidationError(
                "No make-list entries were found. Check the file format or PDF text extraction."
            )

        run.make_list_entries.all().delete()
        objects = [MakeListEntry(boq_run=run, **entry) for entry in entries]
        MakeListEntry.objects.bulk_create(objects, batch_size=500)

        logger.info(
            "Updated make list for BOQ %s run %s with %s entries",
            self.boq.pk,
            run.run_number,
            len(objects),
        )
        return len(objects)
