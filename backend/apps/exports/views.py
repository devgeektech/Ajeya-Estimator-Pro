"""Export views (thin). Ownership mirrors BOQ access rules."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import View

from apps.boq.models import BOQ
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
