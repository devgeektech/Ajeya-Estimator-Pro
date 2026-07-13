"""Parse uploaded make lists (Excel or PDF) into normalized JSON."""
from __future__ import annotations

import logging
from pathlib import Path

from django.core.files.storage import default_storage

from utils.excel import read_rows_with_metadata

from .pdf_make_list_parser import parse_make_list_pdf
from .serial_normalizer import attach_row_hierarchy, detect_serial_key, structure_for_analysis

logger = logging.getLogger("boq_ai")

SCHEMA_VERSION = 1

MAKE_LIST_HEADER_HINTS = frozenset(
    {
        "s_no",
        "sno",
        "sl_no",
        "serial",
        "description",
        "desc",
        "approved_makes",
        "make",
        "material",
        "category",
    }
)


def _resolve_path(uploaded_file) -> str:
    if hasattr(uploaded_file, "temporary_file_path"):
        return uploaded_file.temporary_file_path()
    return default_storage.path(uploaded_file.name)


def _parse_excel_make_list(uploaded_file, *, source_filename: str) -> dict:
    file_path = _resolve_path(uploaded_file)
    headers, records = read_rows_with_metadata(
        file_path,
        header_keys=MAKE_LIST_HEADER_HINTS,
        expand_columns=True,
    )
    serial_key = detect_serial_key(headers)
    rows = attach_row_hierarchy(records, serial_key=serial_key)
    return structure_for_analysis(
        {
            "version": SCHEMA_VERSION,
            "format": "excel",
            "source_filename": source_filename,
            "serial_key": serial_key,
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
        }
    )


def _parse_pdf_make_list(uploaded_file, *, source_filename: str) -> dict:
    file_path = _resolve_path(uploaded_file)
    headers, records = parse_make_list_pdf(file_path)
    serial_key = detect_serial_key(headers)
    rows = attach_row_hierarchy(records, serial_key=serial_key)
    return structure_for_analysis(
        {
            "version": SCHEMA_VERSION,
            "format": "pdf",
            "source_filename": source_filename,
            "serial_key": serial_key,
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
        }
    )


def parse_make_list_file(uploaded_file, *, source_filename: str = "") -> dict:
    """Return normalized make-list JSON from Excel or PDF."""
    name = source_filename or Path(str(uploaded_file)).name
    lower_name = name.lower()
    if lower_name.endswith(".pdf"):
        payload = _parse_pdf_make_list(uploaded_file, source_filename=name)
    elif lower_name.endswith((".xlsx", ".xlsm")):
        payload = _parse_excel_make_list(uploaded_file, source_filename=name)
    else:
        raise ValueError("Make list must be .xlsx, .xlsm, or .pdf")

    logger.info(
        "Parsed make list '%s' (%s): %s rows",
        name,
        payload["format"],
        payload["row_count"],
    )
    return payload
