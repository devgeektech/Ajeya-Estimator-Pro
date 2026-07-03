from django.contrib import admin

from .models import ProcessingJob


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = ("boq_run", "status", "progress", "updated_at")
    list_filter = ("status",)
