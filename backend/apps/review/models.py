"""Review models.

Captures expert modifications to product / rate selection during review
(docs/DATABASE_ARCHITECTURE.md - Review Tables). Experts may change product,
supplier and costs but may not modify the master database
(docs/AGENTS.md - Review Rules).
"""
from django.conf import settings
from django.db import models

from apps.boq.models import BOQItem


class ReviewItem(models.Model):
    boq_item = models.ForeignKey(
        BOQItem, on_delete=models.CASCADE, related_name="review_items"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="reviews",
    )
    original_product = models.CharField(max_length=150, blank=True)
    revised_product = models.CharField(max_length=150, blank=True)
    original_supplier = models.CharField(max_length=150, blank=True)
    revised_supplier = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Review({self.boq_item_id})"
