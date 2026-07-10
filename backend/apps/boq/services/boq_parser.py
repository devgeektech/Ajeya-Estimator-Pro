"""Parse uploaded BOQ workbooks into normalized JSON."""
from __future__ import annotations

import logging
from pathlib import Path

from django.core.files.storage import default_storage

from utils.excel import read_rows_with_metadata

from .serial_normalizer import attach_row_hierarchy, detect_serial_key

logger = logging.getLogger("boq_ai")

SCHEMA_VERSION = 1

BOQ_HEADER_HINTS = frozenset(
    {
        "s_no",
        "sno",
        "sr_no",
        "sl_no",
        "serial",
        "item_no",
        "description",
        "desc",
        "unit",
        "qty",
        "quantity",
        "rate",
        "amount",
        "remarks",
    }
)


def _resolve_path(uploaded_file) -> str:
    if hasattr(uploaded_file, "temporary_file_path"):
        return uploaded_file.temporary_file_path()
    return default_storage.path(uploaded_file.name)


def parse_boq_workbook(uploaded_file, *, source_filename: str = "") -> dict:
    """Return normalized BOQ JSON from an Excel workbook."""
    file_path = _resolve_path(uploaded_file)
    headers, records = read_rows_with_metadata(
        file_path,
        header_keys=BOQ_HEADER_HINTS,
    )
    serial_key = detect_serial_key(headers)
    rows = attach_row_hierarchy(records, serial_key=serial_key)

    payload = {
        "version": SCHEMA_VERSION,
        "format": "excel",
        "source_filename": source_filename or Path(str(uploaded_file)).name,
        "serial_key": serial_key,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
    }
    logger.info(
        "Parsed BOQ workbook '%s': %s rows (serial key: %s)",
        payload["source_filename"],
        len(rows),
        serial_key,
    )
    return payload
