from django.contrib import admin

from .models import BOQ, BOQItem, BOQRun


class BOQRunInline(admin.TabularInline):
    model = BOQRun
    extra = 0


@admin.register(BOQ)
class BOQAdmin(admin.ModelAdmin):
    list_display = ("boq_name", "user", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("boq_name", "user__email")
    inlines = [BOQRunInline]


@admin.register(BOQRun)
class BOQRunAdmin(admin.ModelAdmin):
    list_display = ("boq", "run_number", "status", "started_at", "completed_at")
    list_filter = ("status",)


@admin.register(BOQItem)
class BOQItemAdmin(admin.ModelAdmin):
    list_display = ("boq_run", "row_number", "description", "quantity", "unit")
    search_fields = ("description",)
