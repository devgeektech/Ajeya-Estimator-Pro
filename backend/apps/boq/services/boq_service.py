"""BOQ upload service.

Persists uploaded files, normalizes workbook structure to JSON, and stores
hierarchical rows for later AI extraction and export.
"""
from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record
from apps.boq.models import BOQ
from common.choices import BOQStatus

from .boq_parser import BOQParseError, parse_boq_workbook
from .boq_extract_service import persist_extract_json
from .boq_files import upload_basename
from .make_list_parser import MakeListParseError, parse_make_list_file

logger = logging.getLogger("boq_ai")


class BOQCreationService:
    def __init__(self, user, boq_name, uploaded_file, make_list_file=None):
        self.user = user
        self.boq_name = boq_name
        self.uploaded_file = uploaded_file
        self.make_list_file = make_list_file

    @transaction.atomic
    def run(self) -> BOQ:
        boq = BOQ.objects.create(
            user=self.user,
            boq_name=self.boq_name,
            status=BOQStatus.UPLOADED,
            uploaded_file=self.uploaded_file,
            make_list_file=self.make_list_file,
        )

        try:
            boq.boq_data = parse_boq_workbook(
                boq.uploaded_file,
                source_filename=upload_basename(boq.uploaded_file),
            )
            if self.make_list_file:
                boq.make_list_data = parse_make_list_file(
                    boq.make_list_file,
                    source_filename=upload_basename(boq.make_list_file),
                )
        except (BOQParseError, MakeListParseError, ValueError) as exc:
            logger.exception("BOQ upload parse failed for id=%s", boq.pk)
            # Roll back the BOQ row so failed uploads do not leave empty JSON.
            raise ValidationError(str(exc)) from exc

        if not (boq.boq_data or {}).get("rows"):
            raise ValidationError("BOQ parse produced no data rows.")

        boq.save(update_fields=["boq_data", "make_list_data"])
        persist_extract_json(
            boq,
            boq_data=boq.boq_data,
            make_list_data=boq.make_list_data or None,
            update_database=False,
        )

        logger.info(
            "BOQ uploaded: '%s' (id=%s) by %s",
            boq.boq_name,
            boq.pk,
            self.user.email,
        )
        record(self.user, "Uploaded BOQ", "BOQ", boq.boq_name)
        return boq
