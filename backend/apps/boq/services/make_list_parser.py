"""Parse uploaded make lists (Excel or PDF) into normalized JSON."""
from __future__ import annotations

import logging
from pathlib import Path

from django.core.files.storage import default_storage
from pypdf import PdfReader

from utils.excel import read_rows_with_metadata

from .serial_normalizer import attach_row_hierarchy, detect_serial_key

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
    return {
        "version": SCHEMA_VERSION,
        "format": "excel",
        "source_filename": source_filename,
        "serial_key": serial_key,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
    }


def _parse_pdf_make_list(uploaded_file, *, source_filename: str) -> dict:
    file_path = _resolve_path(uploaded_file)
    reader = PdfReader(file_path)
    rows: list[dict] = []
    line_number = 0
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line_number += 1
            rows.append(
                {
                    "row_id": f"p{page_number}-l{line_number}",
                    "page": page_number,
                    "line": line_number,
                    "serial": "",
                    "depth": 0,
                    "parent_row_id": None,
                    "row_index": line_number,
                    "text": line,
                    "display_values": {"text": line},
                    "values": {"text": line},
                }
            )

    return {
        "version": SCHEMA_VERSION,
        "format": "pdf",
        "source_filename": source_filename,
        "serial_key": None,
        "headers": [{"key": "text", "label": "Text", "index": 0}],
        "rows": rows,
        "row_count": len(rows),
    }


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
