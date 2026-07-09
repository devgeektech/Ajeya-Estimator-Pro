"""Shared enumerations / choices.

Sourced from docs/PRD.md, docs/DATABASE_ARCHITECTURE.md and docs/SESSION_STATE.md.
"""
from django.db import models


class UserRole(models.TextChoices):
    SUPERADMIN = "SUPERADMIN", "Superadmin"
    ADMIN = "ADMIN", "Admin"
    EXPERT = "EXPERT", "Expert"


class BOQStatus(models.TextChoices):
    UPLOADED = "UPLOADED", "Uploaded"
    PROCESSING = "PROCESSING", "Processing"
    COMPLETED = "COMPLETED", "Completed"
    UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
    APPROVED = "APPROVED", "Approved"
    EXPORTED = "EXPORTED", "Exported"


class RunStatus(models.TextChoices):
    QUEUED = "QUEUED", "Queued"
    PROCESSING = "PROCESSING", "Processing"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"
