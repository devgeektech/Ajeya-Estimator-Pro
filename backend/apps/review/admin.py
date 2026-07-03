from django.contrib import admin

from .models import ReviewItem


@admin.register(ReviewItem)
class ReviewItemAdmin(admin.ModelAdmin):
    list_display = ("boq_item", "reviewed_by", "revised_product", "revised_vendor", "created_at")
