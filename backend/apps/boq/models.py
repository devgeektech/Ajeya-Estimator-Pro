"""BOQ models.

Schema sourced from docs/DATABASE_ARCHITECTURE.md (BOQ Tables). Each BOQ is
owned by a single user; reprocessing creates a new BOQRun so historical
results are preserved (docs/AGENTS.md - BOQ Rules).
"""
from django.conf import settings
from django.db import models

from common.choices import BOQStatus, RunStatus


def boq_upload_path(instance, filename):
    return f"boq/{filename}"


def make_list_upload_path(instance, filename):
    return f"make_lists/{filename}"


class BOQ(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="boqs"
    )
    boq_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=BOQStatus.choices, default=BOQStatus.UPLOADED
    )
    uploaded_file = models.FileField(upload_to=boq_upload_path)
    make_list_file = models.FileField(upload_to=make_list_upload_path, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "BOQ"
        verbose_name_plural = "BOQs"

    def __str__(self) -> str:
        return self.boq_name


class BOQRun(models.Model):
    """A single processing run for a BOQ (supports reprocessing history)."""

    boq = models.ForeignKey(BOQ, on_delete=models.CASCADE, related_name="runs")
    run_number = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20, choices=RunStatus.choices, default=RunStatus.QUEUED
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["boq", "-run_number"]
        unique_together = ("boq", "run_number")

    def __str__(self) -> str:
        return f"{self.boq.boq_name} - run {self.run_number}"


class BOQItem(models.Model):
    """An original BOQ row captured from the uploaded workbook."""

    boq_run = models.ForeignKey(BOQRun, on_delete=models.CASCADE, related_name="items")
    row_number = models.PositiveIntegerField()
    description = models.TextField()
    quantity = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    unit = models.CharField(max_length=50, blank=True)
    # AI-extracted structured attributes (product/size/material/make).
    # Populated by the AI analysis stage; null until processed.
    ai_extraction = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["boq_run", "row_number"]

    def __str__(self) -> str:
        return f"Row {self.row_number}: {self.description[:50]}"
