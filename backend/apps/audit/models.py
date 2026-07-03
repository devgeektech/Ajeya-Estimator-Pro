"""Audit models.

Records significant user actions for auditability
(docs/DATABASE_ARCHITECTURE.md - Audit Tables, docs/PRD.md - Security
Requirements). Secrets and passwords are never logged.
"""
from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=150)
    entity = models.CharField(max_length=150, blank=True)
    entity_id = models.CharField(max_length=100, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.action} by {self.user} @ {self.timestamp}"
