"""Pending product views (Super Admin only, thin)."""
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import ListView, View

from apps.audit.services import record
from common.choices import PendingProductStatus
from common.exceptions import BOQAIError
from common.mixins import SuperAdminRequiredMixin

from .models import PendingProduct
from .services.pending_service import PendingProductService

logger = logging.getLogger("boq_ai")


class PendingProductListView(SuperAdminRequiredMixin, ListView):
    template_name = "pending/list.html"
    context_object_name = "pendings"
    paginate_by = 25

    def get_queryset(self):
        return PendingProduct.objects.filter(
            status=PendingProductStatus.PENDING
        ).select_related("boq_item", "created_by").order_by("-created_at")


class _PendingActionView(SuperAdminRequiredMixin, View):
    """Shared lookup + error handling for pending-product actions."""

    audit_action = "pending_action"

    def get_pending(self, pk):
        return get_object_or_404(PendingProduct, pk=pk)

    def handle(self, request, pending):  # pragma: no cover - overridden
        raise NotImplementedError

    def post(self, request, pk):
        pending = self.get_pending(pk)
        try:
            self.handle(request, pending)
            record(request.user, self.audit_action, "PendingProduct", pending.pk)
        except BOQAIError as exc:
            messages.error(request, str(exc))
        return redirect("pending_products:list")


class PendingRejectView(_PendingActionView):
    audit_action = "pending_reject"

    def handle(self, request, pending):
        PendingProductService().reject(pending, request.user)
        messages.success(request, "Pending product rejected.")


class PendingMergeView(_PendingActionView):
    audit_action = "pending_merge"

    def handle(self, request, pending):
        PendingProductService().merge(
            pending, request.POST.get("product_code", ""), user=request.user
        )
        messages.success(request, "Pending product merged into existing product.")


class PendingAddView(_PendingActionView):
    audit_action = "pending_add"

    def handle(self, request, pending):
        PendingProductService().add_new(
            pending,
            product_code=request.POST.get("product_code", ""),
            description=request.POST.get("description", ""),
            purchase_rate=request.POST.get("purchase_rate") or 0,
            make=request.POST.get("make", ""),
            vendor=request.POST.get("vendor", ""),
            unit=request.POST.get("unit", ""),
            user=request.user,
        )
        messages.success(request, "New product added and approved.")
