"""Processing views (thin). Ownership mirrors BOQ access rules."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, View

from apps.boq.models import BOQ, BOQRun
from apps.processing.models import ProcessingJob
from apps.processing.services.job_service import ProcessingJobService


def _owned_boq_qs(user):
    qs = BOQ.objects.all()
    return qs if user.is_super_admin else qs.filter(user=user)


class StartProcessingView(LoginRequiredMixin, View):
    def post(self, request, pk):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        job = ProcessingJobService(boq).start()
        messages.success(
            request, f"Processing queued for '{boq.boq_name}' (run {job.boq_run.run_number})."
        )
        return redirect("boq:detail", pk=boq.pk)


class RunStatusView(LoginRequiredMixin, View):
    """HTMX status fragment for a run's processing job."""

    def get(self, request, pk):
        run = get_object_or_404(
            BOQRun.objects.select_related("boq", "boq__user"), pk=pk
        )
        if not request.user.is_super_admin and run.boq.user_id != request.user.id:
            return render(request, "processing/_status.html", {"run": None, "job": None})
        job = getattr(run, "processing_job", None)
        return render(request, "processing/_status.html", {"run": run, "job": job})


class ProcessingListView(LoginRequiredMixin, ListView):
    template_name = "processing/job_list.html"
    context_object_name = "jobs"
    paginate_by = 10

    def get_queryset(self):
        qs = ProcessingJob.objects.select_related("boq_run", "boq_run__boq", "boq_run__boq__user")
        user = self.request.user
        if not user.is_super_admin:
            qs = qs.filter(boq_run__boq__user=user)
        return qs.order_by("-updated_at")
