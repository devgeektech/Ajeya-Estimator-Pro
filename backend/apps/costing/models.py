"""Rate/labour retrieval models.

Stores selected imported values for a matched BOQ product. This app keeps the
historic Django app label, but the active business rule is retrieval from
Rate_Master and Labour_Master, not cost calculation.
"""
from django.db import models

from apps.matching.models import ProductMatch


class RateDetail(models.Model):
    product_match = models.OneToOneField(
        ProductMatch, on_delete=models.CASCADE, related_name="rate_detail"
    )
    labour_master_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    tech_key = models.CharField(max_length=255, blank=True, db_index=True)
    make = models.CharField(max_length=150, blank=True)
    supplier = models.CharField(max_length=150, blank=True)

    base_purchase_rate = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    net_material_rate = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    commercial_material_base = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    accessories_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    handling_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    wastage_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    subtotal_before_profit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    profit_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    final_expenditure = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    final_amount_excl_gst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    margin_percent_on_selling = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    labour_type = models.CharField(max_length=100, blank=True)
    labour_state = models.CharField(max_length=100, blank=True)
    labour_rate_per_unit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_labour_per_unit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_labour_with_multiplier = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    rate_contribution = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self) -> str:
        return f"RateDetail({self.product_match_id}) = {self.final_amount_excl_gst}"
