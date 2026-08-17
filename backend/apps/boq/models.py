"""BOQ models.

Stores uploaded BOQ workbooks (and optional make lists) for future processing.

Field annotations use Python value types so basedpyright/pyright treat instance
attributes as data (str/dict/…) rather than Django Field descriptors. Runtime
still assigns real Field objects; see ``# type: ignore[assignment]``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Manager
from django.db.models.functions import Lower

from common.choices import BOQStatus


def boq_upload_path(instance, filename):
    return f"boq/{filename}"


def make_list_upload_path(instance, filename):
    return f"make_lists/{filename}"


class BOQ(models.Model):
    objects: ClassVar[Manager[BOQ]] = models.Manager()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="boqs"
    )
    boq_name: str = models.CharField(max_length=255)  # type: ignore[assignment]
    status: str = models.CharField(  # type: ignore[assignment]
        max_length=20, choices=BOQStatus.choices, default=BOQStatus.UPLOADED
    )
    uploaded_file = models.FileField(upload_to=boq_upload_path)
    make_list_file = models.FileField(
        upload_to=make_list_upload_path, blank=True, null=True
    )
    boq_data: dict[str, Any] = models.JSONField(  # type: ignore[assignment]
        default=dict, blank=True, encoder=DjangoJSONEncoder
    )
    make_list_data: dict[str, Any] = models.JSONField(  # type: ignore[assignment]
        default=dict, blank=True, encoder=DjangoJSONEncoder
    )
    analysis_data: dict[str, Any] = models.JSONField(  # type: ignore[assignment]
        default=dict, blank=True, encoder=DjangoJSONEncoder
    )
    created_at: datetime = models.DateTimeField(auto_now_add=True)  # type: ignore[assignment]

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
