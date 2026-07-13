"""BOQ models.

Stores uploaded BOQ workbooks (and optional make lists) for future processing.
"""
from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from common.choices import BOQStatus


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
    make_list_file = models.FileField(
        upload_to=make_list_upload_path, blank=True, null=True
    )
    boq_data = models.JSONField(default=dict, blank=True)
    make_list_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "BOQ"
        verbose_name_plural = "BOQs"
        constraints = [
            models.UniqueConstraint(
                Lower("boq_name"),
                name="boq_unique_name_ci",
            )
        ]

    def __str__(self) -> str:
        return self.boq_name
