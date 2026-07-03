"""Pending product models.

Products that score below the confidence threshold (< 30%) are left blank in
output and queued here for Super Admin approval
(docs/PRD.md - Pending Product Workflow, docs/AGENTS.md - Pending Product Rules).
"""
from django.conf import settings
from django.db import models

from apps.boq.models import BOQItem
from common.choices import PendingProductStatus


class PendingProduct(models.Model):
    description = models.TextField()
    suggested_product = models.CharField(max_length=255, blank=True)
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    boq_item = models.ForeignKey(
        BOQItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pending_products",
    )
    status = models.CharField(
        max_length=20,
        choices=PendingProductStatus.choices,
        default=PendingProductStatus.PENDING,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_pending_products",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_pending_products",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Pending: {self.description[:50]} ({self.status})"
