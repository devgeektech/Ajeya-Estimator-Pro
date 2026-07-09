"""Export models.

Records generated export workbooks. Each export produces a linked internal
review sheet and client sheet (docs/ARCHITECTURE.md - Export Architecture).
"""
from django.conf import settings
from django.db import models

from apps.boq.models import BOQRun


def export_upload_path(instance, filename):
    return f"exports/{filename}"


class ExportFile(models.Model):
    boq_run = models.ForeignKey(
        BOQRun, on_delete=models.CASCADE, related_name="exports"
    )
    internal_sheet = models.FileField(upload_to=export_upload_path, blank=True, null=True)
    client_sheet = models.FileField(upload_to=export_upload_path, blank=True, null=True)
    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="exports",
    )
    exported_at = models.DateTimeField(auto_now_add=True)
    is_preview = models.BooleanField(
        default=False,
        help_text="Draft workbook generated before approval/export.",
    )

    class Meta:
        ordering = ["-exported_at"]

    def __str__(self) -> str:
        return f"Export({self.boq_run})"
