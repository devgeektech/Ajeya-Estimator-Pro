"""Shared enumerations / choices."""
from django.db import models


class UserRole(models.TextChoices):
    SUPERADMIN = "SUPERADMIN", "Superadmin"
    ADMIN = "ADMIN", "Admin"
    EXPERT = "EXPERT", "Expert"


class BOQStatus(models.TextChoices):
    UPLOADED = "UPLOADED", "Uploaded"
