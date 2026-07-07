"""Review views (thin). Ownership mirrors BOQ access rules."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View

from apps.boq.models import BOQ, BOQItem
from apps.database_manager.models import RateMaster
from apps.matching.services.confidence import band_for
from apps.review.services.review_service import ReviewService
from common.exceptions import ValidationError

logger = logging.getLogger("boq_ai")


def _owned_boq_qs(user):
    qs = BOQ.objects.select_related("user")
    return qs if user.is_super_admin else qs.filter(user=user)


def _row_context(item, service: ReviewService):
    """Build the per-row context (match, cost, band, candidate rate options)."""
    match = item.product_matches.first()
    breakdown = getattr(match, "cost_breakdown", None) if match else None
    return {
        "item": item,
        "match": match,
        "breakdown": breakdown,
        "band": band_for(match.confidence_score) if match else "blank",
        "candidates": service.candidate_rates(item),
    }


class ReviewView(LoginRequiredMixin, View):
    """Editable review of the latest run's results."""

    def get(self, request, pk):
        boq = get_object_or_404(_owned_boq_qs(request.user), pk=pk)
        run = boq.runs.order_by("-run_number").first()
        service = ReviewService()
        rows = []
        if run:
            items = run.items.prefetch_related("product_matches").all()
            rows = [_row_context(item, service) for item in items]
        latest_export = run.exports.first() if run else None
        return render(
            request,
            "review/review.html",
            {"boq": boq, "run": run, "rows": rows, "latest_export": latest_export},
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

        if request.headers.get("HX-Request"):
            return render(
                request, "review/_row.html", {"row": _row_context(item, service)}
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
