"""BOQ upload service.

Persists the uploaded workbook and optional make list. Parsing and processing are
handled in a later workflow rebuild.
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.audit.services import record
from apps.boq.models import BOQ
from common.choices import BOQStatus

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
        logger.info(
            "BOQ uploaded: '%s' (id=%s) by %s",
            boq.boq_name,
            boq.pk,
            self.user.email,
        )
        record(self.user, "Uploaded BOQ", "BOQ", boq.boq_name)
        return boq
