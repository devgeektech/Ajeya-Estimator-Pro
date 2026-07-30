"""Shared enumerations / choices."""
from django.db import models


class UserRole(models.TextChoices):
    SUPERADMIN = "SUPERADMIN", "Superadmin"
    ADMIN = "ADMIN", "Admin"
    EXPERT = "EXPERT", "Expert"


class BOQStatus(models.TextChoices):
    UPLOADED = "UPLOADED", "Uploaded"
    PROCESSING = "PROCESSING", "Analysing..."
    EXTRACTED = "EXTRACTED", "Analysed"
    MAKE_VENDOR = "MAKE_VENDOR", "Make/Vendor selection"
    LABOUR = "LABOUR", "Labour"
    MATCHING = "MATCHING", "Matching"  # legacy (unused in active UI)
    PROCESSED = "PROCESSED", "Matched"  # legacy (unused in active UI)
    READY_EXPORT = "READY_EXPORT", "Ready to Export"
    EXPORTED = "EXPORTED", "Exported"
    ANALYSIS_FAILED = "ANALYSIS_FAILED", "Analysis Failed"
