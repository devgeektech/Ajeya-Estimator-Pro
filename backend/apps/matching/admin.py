from django.contrib import admin

from .models import ActivityMatch, ProductMatch


@admin.register(ProductMatch)
class ProductMatchAdmin(admin.ModelAdmin):
    list_display = ("boq_item", "product", "make", "supplier", "confidence_score")
    list_filter = ("make", "supplier")


@admin.register(ActivityMatch)
class ActivityMatchAdmin(admin.ModelAdmin):
    list_display = ("boq_item", "activity_name", "confidence_score")
