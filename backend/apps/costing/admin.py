from django.contrib import admin

from .models import RateDetail


@admin.register(RateDetail)
class RateDetailAdmin(admin.ModelAdmin):
    list_display = (
        "product_match",
        "tech_key",
        "supplier",
        "final_amount_excl_gst",
        "rate_contribution",
        "total_labour_with_multiplier",
    )
