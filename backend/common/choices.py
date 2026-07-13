"""Shared enumerations / choices."""
from django.db import models


class UserRole(models.TextChoices):
    SUPERADMIN = "SUPERADMIN", "Superadmin"
    ADMIN = "ADMIN", "Admin"
    EXPERT = "EXPERT", "Expert"


class BOQStatus(models.TextChoices):
    UPLOADED = "UPLOADED", "Uploaded"
    PROCESSING = "PROCESSING", "Processing"
    EXTRACTED = "EXTRACTED", "Extracted"
    MATCHING = "MATCHING", "Matching"
    PROCESSED = "PROCESSED", "Processed"
    ANALYSIS_FAILED = "ANALYSIS_FAILED", "Analysis Failed"
