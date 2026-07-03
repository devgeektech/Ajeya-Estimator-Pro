"""Costing models.

Stores the rule-based cost breakdown for a matched BOQ item
(docs/DATABASE_ARCHITECTURE.md - Cost Tables). AI never performs these
calculations (docs/AGENTS.md - AI Rules).

Final rate = material + labour + transportation + accessories + overheads + profit.
"""
from django.db import models

from apps.matching.models import ProductMatch


class CostBreakdown(models.Model):
    product_match = models.OneToOneField(
        ProductMatch, on_delete=models.CASCADE, related_name="cost_breakdown"
    )
    material_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    labour_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    transportation_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    accessories_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    overhead_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    profit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    final_rate = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self) -> str:
        return f"Cost({self.product_match_id}) = {self.final_rate}"
