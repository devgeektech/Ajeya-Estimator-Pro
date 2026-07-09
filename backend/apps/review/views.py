"""Review views (thin). Ownership mirrors BOQ access rules."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View

from apps.boq.models import BOQ, BOQItem
from apps.database_manager.models import RateMaster
from apps.exports.services.export_service import ExportService
from apps.review.services.review_service import ReviewService
from apps.review.services.row_context import build_review_row_context, build_review_summary
from common.exceptions import ValidationError

logger = logging.getLogger("boq_ai")


def _owned_boq_qs(user):
    qs = BOQ.objects.select_related("user")
    return qs if user.is_super_admin else qs.filter(user=user)


class ReviewView(LoginRequiredMixin, View):
    """Editable review of the latest run's results."""

    def get(self, request, pk):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        run = boq.runs.order_by("-run_number").first()
        service = ReviewService()
        rows = []
        if run:
            items = run.items.prefetch_related(
                "product_matches__product",
                "product_matches__rate_detail",
            ).all()
            rows = [build_review_row_context(item, service) for item in items]
        latest_export = run.exports.filter(is_preview=False).first() if run else None
        latest_preview = run.exports.filter(is_preview=True).first() if run else None
        return render(
            request,
            "review/review.html",
            {
                "boq": boq,
                "run": run,
                "rows": rows,
                "summary": build_review_summary(rows),
                "latest_export": latest_export,
                "latest_preview": latest_preview,
            },
        )


class ApplyReviewView(LoginRequiredMixin, View):
    """Apply a product/rate change to one item (HTMX row swap)."""

    def post(self, request, item_id):
        item = get_object_or_404(
            BOQItem.objects.select_related("boq_run__boq"), pk=item_id
        )
        boq = item.boq_run.boq
        if not request.user.is_super_admin and boq.user_id != request.user.id:
            return render(request, "review/_row.html", {"row": None}, status=403)

        rate = get_object_or_404(RateMaster, pk=request.POST.get("rate_id"))
        service = ReviewService()
        service.apply_selection(item, rate, user=request.user)
        item = BOQItem.objects.prefetch_related(
            "product_matches__product",
            "product_matches__rate_detail",
        ).get(pk=item.pk)

        if request.headers.get("HX-Request"):
            return render(
                request,
                "review/_row.html",
                {"row": build_review_row_context(item, service)},
            )
        messages.success(request, "Row updated.")
        return redirect("review:detail", pk=boq.pk)


class StartReviewView(LoginRequiredMixin, View):
    def post(self, request, pk):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        ReviewService().start_review(boq, request.user)
        messages.success(request, f"'{boq.boq_name}' is now under review.")
        return redirect("review:detail", pk=boq.pk)


class ApproveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        try:
            ReviewService().approve(boq, request.user)
            messages.success(request, f"'{boq.boq_name}' approved.")
        except ValidationError as exc:
            messages.error(request, str(exc))
        return redirect("review:detail", pk=boq.pk)


class ReviseView(LoginRequiredMixin, View):
    def post(self, request, pk):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        try:
            ReviewService().revise(boq, request.user)
            messages.success(request, f"'{boq.boq_name}' reopened for review.")
        except ValidationError as exc:
            messages.error(request, str(exc))
        return redirect("review:detail", pk=boq.pk)


class PreviewExportView(LoginRequiredMixin, View):
    """Generate a draft Breakdown + Client BOQ workbook before approval."""

    def post(self, request, pk):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        run = boq.runs.order_by("-run_number").first()
        if run is None:
            messages.error(request, "Nothing to preview yet.")
            return redirect("review:detail", pk=boq.pk)
        try:
            ExportService().preview_run(run, request.user)
            messages.success(
                request,
                "Draft preview workbook generated. Download it before approving.",
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        return redirect("review:detail", pk=boq.pk)
