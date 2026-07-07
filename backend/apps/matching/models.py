"""Matching models.

Stores product and activity matches per BOQ item (docs/DATABASE_ARCHITECTURE.md
- Matching Tables). Confidence and the match reason are persisted so the
review workflow and exports can explain each result.
"""
from django.db import models

from apps.boq.models import BOQItem
from apps.database_manager.models import RateMaster


class ProductMatch(models.Model):
    boq_item = models.ForeignKey(
        BOQItem, on_delete=models.CASCADE, related_name="product_matches"
    )
    product = models.ForeignKey(
        RateMaster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matches",
    )
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    make = models.CharField(max_length=150, blank=True)
    vendor = models.CharField(max_length=150, blank=True)
    match_reason = models.CharField(max_length=255, blank=True)
    ai_explanation = models.TextField(blank=True)

    class Meta:
        ordering = ["boq_item", "-confidence_score"]

    def __str__(self) -> str:
        return f"Match({self.boq_item_id}) {self.confidence_score}%"


class ActivityMatch(models.Model):
    boq_item = models.ForeignKey(
        BOQItem, on_delete=models.CASCADE, related_name="activity_matches"
    )
    activity_name = models.CharField(max_length=150)
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    def __str__(self) -> str:
        return self.activity_name
