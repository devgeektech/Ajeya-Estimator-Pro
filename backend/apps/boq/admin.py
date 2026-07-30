from django.contrib import admin

from .models import BOQ


@admin.register(BOQ)
class BOQAdmin(admin.ModelAdmin):
    list_display = ("boq_name", "user", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("boq_name", "user__email")
