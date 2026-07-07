"""Export views (thin). Ownership mirrors BOQ access rules."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import View

from apps.boq.models import BOQ
from apps.exports.models import ExportFile
from apps.exports.services.export_service import ExportService
from common.exceptions import BOQAIError

logger = logging.getLogger("boq_ai")


def _owned_boq_qs(user):
    qs = BOQ.objects.select_related("user")
    return qs if user.is_super_admin else qs.filter(user=user)


class GenerateExportView(LoginRequiredMixin, View):
    def post(self, request, pk):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        run = boq.runs.order_by("-run_number").first()
        if run is None:
            messages.error(request, "Nothing to export yet.")
            return redirect("review:detail", pk=boq.pk)
        try:
            ExportService().export_run(run, request.user)
            messages.success(request, f"'{boq.boq_name}' exported.")
        except BOQAIError as exc:
            messages.error(request, str(exc))
        return redirect("review:detail", pk=boq.pk)


class DownloadExportView(LoginRequiredMixin, View):
    """Download a generated client BOQ or breakdown workbook."""

    def get(self, request, pk, kind):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        run = boq.runs.order_by("-run_number").first()
        export = run.exports.first() if run else None
        if export is None:
            messages.error(request, "No export file is available yet.")
            return redirect("review:detail", pk=boq.pk)

        field, filename = self._file_for_kind(export, kind)
        if field is None or not field or not field.storage.exists(field.name):
            messages.error(request, "Export file not found.")
            return redirect("review:detail", pk=boq.pk)
        return FileResponse(field.open("rb"), as_attachment=True, filename=filename)

    def _file_for_kind(self, export: ExportFile, kind: str):
        prefix = f"boq{export.boq_run.boq_id}_run{export.boq_run.run_number}"
        if kind == "client":
            return export.client_sheet, f"{prefix}_client_boq.xlsx"
        if kind == "breakdown":
            return export.internal_sheet, f"{prefix}_breakdown_list.xlsx"
        return None, ""
