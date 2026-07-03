"""Processing job models.

Tracks asynchronous BOQ processing jobs and their progress
(docs/ARCHITECTURE.md - Background Job Architecture). All heavy processing
runs through Celery; this model records status for the UI.
"""
from django.db import models

from apps.boq.models import BOQRun
from common.choices import RunStatus


class ProcessingJob(models.Model):
    boq_run = models.OneToOneField(
        BOQRun, on_delete=models.CASCADE, related_name="processing_job"
    )
    status = models.CharField(
        max_length=20, choices=RunStatus.choices, default=RunStatus.QUEUED
    )
    progress = models.PositiveSmallIntegerField(default=0)  # 0-100
    message = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Job({self.boq_run}) - {self.status} {self.progress}%"
