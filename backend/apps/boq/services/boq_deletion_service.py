"""Delete a BOQ and all on-disk residuals keyed to it."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction

from apps.audit.services import record
from apps.boq.models import BOQ
from apps.boq.services.boq_job_progress import clear_boq_job_progress
from apps.boq.services.extract_json_store import boq_extract_dir, delete_extract_json_dir

logger = logging.getLogger("boq_ai")


class BOQDeletionService:
    """Remove DB row + media files for one BOQ (visibility checked by the view)."""

    def __init__(self, *, actor=None):
        self.actor = actor

    def delete(self, boq: BOQ) -> dict[str, Any]:
        """Delete BOQ row and residuals. Returns a summary for logging/messages."""
        boq_id = int(boq.pk)
        boq_name = str(boq.boq_name)
        uploaded_name = getattr(boq.uploaded_file, "name", "") or ""
        make_list_name = getattr(boq.make_list_file, "name", "") or ""

        extract_dir = boq_extract_dir(boq_name)
        summary = {
            "boq_id": boq_id,
            "boq_name": boq_name,
            "uploaded_file": uploaded_name,
            "make_list_file": make_list_name,
            "extract_dir": str(extract_dir),
        }

        self._delete_file_field(boq.uploaded_file, label="BOQ workbook")
        self._delete_file_field(boq.make_list_file, label="make list")
        delete_extract_json_dir(boq_name)
        clear_boq_job_progress(boq_id)
        self._clear_progress_tmp_files(boq_id)

        with transaction.atomic():
            # Re-fetch under lock so a concurrent job cannot resurrect state.
            locked = BOQ.objects.select_for_update().filter(pk=boq_id).first()
            if locked is None:
                logger.info("BOQ id=%s already deleted", boq_id)
                return summary
            owner = getattr(locked, "user", None)
            locked.delete()

        # Audit the actor who deleted so Admin/Superadmin can see Expert (or
        # self) deletions in Audit Log → that user's entries.
        owner_email = getattr(owner, "email", "") or ""
        actor_email = getattr(self.actor, "email", "") or ""
        if owner_email and actor_email and owner_email.lower() != actor_email.lower():
            action = f"Deleted BOQ '{boq_name}' (owner: {owner_email})"
        else:
            action = f"Deleted BOQ '{boq_name}'"
        entity_id = boq_name[:100]
        record(self.actor, action, "BOQ", entity_id)
        logger.info(
            "Deleted BOQ id=%s name=%r files=%s / %s extract=%s",
            boq_id,
            boq_name,
            uploaded_name,
            make_list_name,
            extract_dir,
        )
        return summary

    @staticmethod
    def _delete_file_field(file_field, *, label: str) -> None:
        if not file_field or not getattr(file_field, "name", None):
            return
        try:
            file_field.delete(save=False)
        except Exception:
            logger.exception("Failed deleting %s file %s", label, file_field.name)

    @staticmethod
    def _clear_progress_tmp_files(boq_id: int) -> None:
        progress_dir = Path(settings.MEDIA_ROOT) / "job_progress"
        if not progress_dir.is_dir():
            return
        for path in progress_dir.glob(f"{boq_id}.*.tmp"):
            try:
                path.unlink()
            except OSError:
                logger.warning("Could not remove progress temp file %s", path)
