from django.contrib import admin

from .models import CostBreakdown


@admin.register(CostBreakdown)
class CostBreakdownAdmin(admin.ModelAdmin):
    list_display = (
        "product_match",
        "material_cost",
        "labour_cost",
        "overhead_cost",
        "profit",
        "final_rate",
    )
