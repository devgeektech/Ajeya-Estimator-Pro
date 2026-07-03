from django.contrib import admin

from .models import ExportFile


@admin.register(ExportFile)
class ExportFileAdmin(admin.ModelAdmin):
    list_display = ("boq_run", "exported_by", "exported_at")
