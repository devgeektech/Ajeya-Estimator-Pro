from django.contrib import admin

from .models import PendingProduct


@admin.register(PendingProduct)
class PendingProductAdmin(admin.ModelAdmin):
    list_display = ("description", "suggested_product", "confidence_score", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("description", "suggested_product")
