from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "entity", "entity_id", "timestamp")
    list_filter = ("action",)
    search_fields = ("action", "entity", "entity_id")
    readonly_fields = ("user", "action", "entity", "entity_id", "timestamp")
