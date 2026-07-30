"""Parse uploaded BOQ workbooks into normalized JSON."""
from __future__ import annotations

import logging
from pathlib import Path

from django.core.files.storage import default_storage

from utils.excel import MultiSheetWorkbookError, read_rows_with_metadata, require_single_worksheet

from .serial_normalizer import attach_row_hierarchy, detect_serial_key, structure_for_analysis

logger = logging.getLogger("boq_ai")

SCHEMA_VERSION = 1

BOQ_HEADER_HINTS = frozenset(
    {
        "s_no",
        "sno",
        "sr_no",
        "sl_no",
        "serial",
        "serial_no",
        "item_no",
        "item",
        "description",
        "desc",
        "particulars",
        "item_description",
        "unit",
        "uom",
        "qty",
        "quantity",
        "qnty",
        "nos",
        "total",
        "ground",
        "basement",
        "rate",
        "amount",
        "remarks",
        "size",
        "dia",
        "nb",
    }
)


class BOQParseError(ValueError):
    """Raised when a BOQ workbook cannot be normalized into rows."""


def _resolve_path(uploaded_file) -> str:
    if hasattr(uploaded_file, "temporary_file_path"):
        return uploaded_file.temporary_file_path()
    return default_storage.path(uploaded_file.name)


def parse_boq_workbook(uploaded_file, *, source_filename: str = "") -> dict:
    """Return normalized BOQ JSON from an Excel workbook.

    Raises ``BOQParseError`` when no usable headers/rows are found.
    """
    file_path = _resolve_path(uploaded_file)
    try:
        require_single_worksheet(file_path, detail_label="BOQ details")
    except MultiSheetWorkbookError as exc:
        raise BOQParseError(str(exc)) from exc
    headers, records = read_rows_with_metadata(
        file_path,
        header_keys=BOQ_HEADER_HINTS,
        expand_columns=True,
        merge_matching_sheets=False,
        min_header_matches=2,
    )
    if not headers or not records:
        raise BOQParseError(
            "Could not find a BOQ table with recognizable headers and data rows. "
            "Ensure the workbook has S.No / Description / Qty-style columns."
        )

    serial_key = detect_serial_key(headers)
    rows = attach_row_hierarchy(records, serial_key=serial_key)
    sheet_names = sorted(
        {str(row.get("sheet_name") or "") for row in rows if row.get("sheet_name")}
    )

    payload = structure_for_analysis(
        {
            "version": SCHEMA_VERSION,
            "format": "excel",
            "source_filename": source_filename or Path(str(uploaded_file)).name,
            "serial_key": serial_key,
            "headers": headers,
            "sheets": sheet_names,
            "rows": rows,
            "row_count": len(rows),
        }
    )
    logger.info(
        "Parsed BOQ workbook '%s': %s rows across %s sheet(s) (serial key: %s)",
        payload["source_filename"],
        len(rows),
        len(sheet_names) or 1,
        serial_key,
    )
    return payload
