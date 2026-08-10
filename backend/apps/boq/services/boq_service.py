"""BOQ upload service.

Persists uploaded files, normalizes workbook structure to JSON, and stores
hierarchical rows for later AI extraction and export.
"""
from __future__ import annotations

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record
from apps.boq.models import BOQ
from common.choices import BOQStatus

from .boq_parser import BOQParseError, parse_boq_workbook
from .boq_extract_service import persist_extract_json
from .boq_files import upload_basename
from .make_list_parser import MakeListParseError, parse_make_list_file
from .xls_upload_conversion_service import XlsUploadConversionService
from utils.excel import MultiSheetWorkbookError, require_single_worksheet
from utils.xls_convert import XlsConvertError, is_xls_filename

logger = logging.getLogger("boq_ai")

_EXCEL_EXTS = (".xlsx", ".xlsm", ".xls")


def _resolve_upload_path(uploaded_file) -> tuple[str, str | None]:
    """Return ``(path, temp_path_to_delete_or_None)`` for an uploaded file."""
    if hasattr(uploaded_file, "temporary_file_path"):
        return uploaded_file.temporary_file_path(), None
    suffix = Path(upload_basename(uploaded_file)).suffix or ".bin"
    handle = NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)
        handle.close()
        return handle.name, handle.name
    except Exception:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise


def _ensure_single_excel_sheet(uploaded_file, *, detail_label: str) -> None:
    """Reject Excel uploads that contain more than one visible worksheet."""
    if not uploaded_file:
        return
    name = upload_basename(uploaded_file).lower()
    if name.endswith(".pdf"):
        return
    if not (name.endswith(_EXCEL_EXTS) or is_xls_filename(name)):
        return
    path, temp_path = _resolve_upload_path(uploaded_file)
    try:
        sheet = require_single_worksheet(path, detail_label=detail_label)
        logger.info("Upload sheet check ok for '%s': %s", name, sheet)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
        # Reset pointer so later convert / FileField save can re-read the upload.
        seek = getattr(uploaded_file, "seek", None)
        if callable(seek):
            try:
                seek(0)
            except Exception:
                pass


class BOQCreationService:
    def __init__(self, user, boq_name, uploaded_file, make_list_file=None):
        self.user = user
        self.boq_name = boq_name
        self.uploaded_file = uploaded_file
        self.make_list_file = make_list_file

    @transaction.atomic
    def run(self) -> BOQ:
        from apps.database_manager.services.activation import get_active_database_version

        if get_active_database_version() is None:
            raise ValidationError(
                "No active master database is available. Upload and activate a "
                "database first, then upload the BOQ."
            )

        try:
            # Validate original files before convert/persist (visible sheets only).
            _ensure_single_excel_sheet(self.uploaded_file, detail_label="BOQ details")
            _ensure_single_excel_sheet(self.make_list_file, detail_label="make list details")
        except MultiSheetWorkbookError as exc:
            raise ValidationError(str(exc)) from exc

        converter = XlsUploadConversionService()
        try:
            uploaded_file = converter.maybe_convert(self.uploaded_file)
            make_list_file = converter.maybe_convert(self.make_list_file)
        except XlsConvertError as exc:
            raise ValidationError(str(exc)) from exc

        boq = BOQ.objects.create(
            user=self.user,
            boq_name=self.boq_name,
            status=BOQStatus.UPLOADED,
            uploaded_file=uploaded_file,
            make_list_file=make_list_file,
        )

        try:
            boq.boq_data = parse_boq_workbook(
                boq.uploaded_file,
                source_filename=upload_basename(boq.uploaded_file),
            )
            if make_list_file:
                boq.make_list_data = parse_make_list_file(
                    boq.make_list_file,
                    source_filename=upload_basename(boq.make_list_file),
                )
        except (
            BOQParseError,
            MakeListParseError,
            MultiSheetWorkbookError,
            XlsConvertError,
            ValueError,
        ) as exc:
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
