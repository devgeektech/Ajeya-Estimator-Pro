"""Export service (Phase 10, Sprint 19).

Generates the two-sheet internal workbook (Internal Review + linked Client BOQ)
and a standalone client workbook, persists them on an ExportFile, and moves the
BOQ to Exported (docs/PRD.md - Output Strategy; BOQ Workflow). Export requires an
approved BOQ.
"""
from __future__ import annotations

import io
import logging

from django.core.files.base import ContentFile
from openpyxl import Workbook

from apps.audit.services import record
from apps.exports.models import ExportFile
from apps.notifications.services import notify
from common.choices import BOQStatus
from common.exceptions import ValidationError

from exports.client_sheet import write_client_sheet
from exports.internal_sheet import BREAKDOWN_SHEET_TITLE, write_internal_sheet

logger = logging.getLogger("boq_ai")


def _workbook_bytes(wb) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class ExportService:
    """Build and persist export workbooks for an approved BOQ run."""

    _PREVIEW_FROM = {
        BOQStatus.COMPLETED,
        BOQStatus.UNDER_REVIEW,
        BOQStatus.APPROVED,
    }

    @staticmethod
    def _build_internal_workbook(run):
        internal_wb = Workbook()
        write_internal_sheet(internal_wb.active, run)
        write_client_sheet(
            internal_wb.create_sheet("Client BOQ"), run, link_sheet=BREAKDOWN_SHEET_TITLE
        )
        return internal_wb

    def preview_run(self, run, user=None):
        """Generate a draft 2-sheet workbook without changing BOQ status."""
        boq = run.boq
        if boq.status not in self._PREVIEW_FROM:
            raise ValidationError(
                f"Preview is not available for '{boq.get_status_display()}' BOQs."
            )

        internal_wb = self._build_internal_workbook(run)
        prefix = f"boq{boq.pk}_run{run.run_number}_preview"
        export = ExportFile(boq_run=run, exported_by=user, is_preview=True)
        export.internal_sheet.save(
            f"{prefix}_internal.xlsx",
            ContentFile(_workbook_bytes(internal_wb)),
            save=False,
        )
        export.save()
        ExportFile.objects.filter(boq_run=run, is_preview=True).exclude(pk=export.pk).delete()
        logger.info("BOQ %s preview workbook generated (run %s)", boq.pk, run.run_number)
        return export

    def export_run(self, run, user=None):
        boq = run.boq
        if boq.status != BOQStatus.APPROVED:
            raise ValidationError(
                f"Only approved BOQs can be exported (current: '{boq.get_status_display()}')."
            )

        # Internal workbook: Breakdown List + linked Client BOQ.
        internal_wb = self._build_internal_workbook(run)

        # Standalone client workbook (computed values, safe to share).
        client_wb = Workbook()
        write_client_sheet(client_wb.active, run, link_sheet=None)

        prefix = f"boq{boq.pk}_run{run.run_number}"
        ExportFile.objects.filter(boq_run=run, is_preview=True).delete()
        export = ExportFile(boq_run=run, exported_by=user, is_preview=False)
        export.internal_sheet.save(
            f"{prefix}_internal.xlsx", ContentFile(_workbook_bytes(internal_wb)), save=False
        )
        export.client_sheet.save(
            f"{prefix}_client.xlsx", ContentFile(_workbook_bytes(client_wb)), save=False
        )
        export.save()

        boq.status = BOQStatus.EXPORTED
        boq.save(update_fields=["status"])
        logger.info("BOQ %s exported (run %s)", boq.pk, run.run_number)

        record(user, "export", "BOQ", boq.pk)
        notify(boq.user, "Export ready", f"'{boq.boq_name}' has been exported.")
        return export
