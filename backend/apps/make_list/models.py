"""Make list models.

The make list acts as the source of truth for approved makes and is applied
as a filtering layer during product matching (docs/PRD.md - Make List
Processing). It is parsed per BOQ run; approved makes are stored as entries.
"""
from django.db import models

from apps.boq.models import BOQRun


class MakeListEntry(models.Model):
    """An approved make for a given BOQ run."""

    boq_run = models.ForeignKey(
        BOQRun, on_delete=models.CASCADE, related_name="make_list_entries"
    )
    make = models.CharField(max_length=150, db_index=True)
    category = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name_plural = "Make list entries"

    def __str__(self) -> str:
        return self.make
