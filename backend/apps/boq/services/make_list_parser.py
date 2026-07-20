"""Parse uploaded make lists (Excel or PDF) into normalized JSON."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from django.core.files.storage import default_storage

from utils.excel import read_rows_with_metadata, score_make_list_sheet
from utils.make_list_splits import attach_approved_makes_list

from .pdf_make_list_parser import parse_make_list_pdf
from .serial_normalizer import attach_row_hierarchy, detect_serial_key, structure_for_analysis

logger = logging.getLogger("boq_ai")

SCHEMA_VERSION = 2

MAKE_LIST_HEADER_HINTS = frozenset(
    {
        "s_no",
        "sno",
        "sl_no",
        "serial",
        "description",
        "desc",
        "particulars",
        "approved_makes",
        "approved_make",
        "make",
        "makes",
        "manufacturer",
        "manufacturers",
        "brand",
        "brands",
        "material",
        "materials",
        "make_manufacturers_name",
        "make_manufacturer",
    }
)

_HEADER_LIKE = re.compile(
    r"^(s\.?\s*no\.?|sl\.?\s*no\.?|serial|description|particulars|material|"
    r"approved\s*makes?|make|amount|qty|quantity|unit|rate)$",
    re.IGNORECASE,
)


class MakeListParseError(ValueError):
    """Raised when a make list cannot be normalized into rows."""


def _resolve_path(uploaded_file) -> str:
    if hasattr(uploaded_file, "temporary_file_path"):
        return uploaded_file.temporary_file_path()
    return default_storage.path(uploaded_file.name)


def _is_junk_make_list_row(row: dict, *, serial_key: str | None, material_key: str) -> bool:
    """Drop repeated header rows and rate-sheet leftovers."""
    display = row.get("display_values") or {}
    serial = str(display.get(serial_key) or row.get("serial") or "").strip()
    material = str(display.get(material_key) or "").strip()
    makes = row.get("approved_makes_list") or []

    if _HEADER_LIKE.match(serial) or _HEADER_LIKE.match(material):
        return True
    if not material and not makes:
        return True
    # Lone serial with no material/makes (section junk).
    if serial and not material and not makes:
        return True
    return False


def slim_make_list_payload(payload: dict) -> dict:
    """Keep only serial + material/description + make columns and clean rows."""
    roles = payload.get("column_roles") or {}
    serial_key = payload.get("serial_key")
    material_keys = list(roles.get("material_keys") or [])
    make_keys = list(roles.get("make_keys") or [])

    material_key = next(
        (
            key
            for key in (*material_keys, "description", "material", "particulars", "desc")
            if key
        ),
        "description",
    )

    keep_keys: list[str] = []
    for key in (serial_key, material_key, *make_keys):
        if key and key not in keep_keys:
            keep_keys.append(key)

    header_by_key = {
        str(header.get("key")): header for header in (payload.get("headers") or [])
    }
    slim_headers = []
    for key in keep_keys:
        header = header_by_key.get(key)
        if header:
            slim_headers.append(header)
        else:
            slim_headers.append({"key": key, "label": key.replace("_", " ").title(), "index": len(slim_headers)})

    slim_rows: list[dict] = []
    for row in payload.get("rows") or []:
        if _is_junk_make_list_row(row, serial_key=serial_key, material_key=material_key):
            continue
        display = row.get("display_values") or {}
        values = row.get("values") or {}
        slim_display = {key: display.get(key) for key in keep_keys}
        slim_values = {key: values.get(key) for key in keep_keys}
        # Drop rows that still have no material and no makes after slim.
        material = str(slim_display.get(material_key) or "").strip()
        makes = row.get("approved_makes_list") or []
        if not material and not makes:
            continue
        slim_rows.append(
            {
                **row,
                "display_values": slim_display,
                "values": slim_values,
                "approved_makes_list": list(makes),
            }
        )

    sheet_names = sorted(
        {
            str(row.get("sheet_name") or "")
            for row in slim_rows
            if row.get("sheet_name")
        }
    )
    return structure_for_analysis(
        {
            **payload,
            "headers": slim_headers,
            "rows": slim_rows,
            "row_count": len(slim_rows),
            "sheets": sheet_names,
            "column_roles": {
                "make_keys": [key for key in make_keys if key in keep_keys],
                "material_keys": [material_key],
            },
        }
    )


def _parse_excel_make_list(uploaded_file, *, source_filename: str) -> dict:
    file_path = _resolve_path(uploaded_file)
    # Single best make-list sheet only (score prefers "MAKE LIST", not giant rate sheets).
    headers, records = read_rows_with_metadata(
        file_path,
        header_keys=MAKE_LIST_HEADER_HINTS,
        expand_columns=True,
        merge_matching_sheets=False,
        sheet_score_fn=score_make_list_sheet,
    )
    if not headers or not records:
        raise MakeListParseError(
            "Could not find a make-list table with recognizable headers and data rows."
        )
    serial_key = detect_serial_key(headers)
    rows, column_roles = attach_approved_makes_list(
        attach_row_hierarchy(records, serial_key=serial_key),
        headers=headers,
    )
    payload = {
        "version": SCHEMA_VERSION,
        "format": "excel",
        "source_filename": source_filename,
        "serial_key": serial_key,
        "headers": headers,
        "column_roles": column_roles,
        "rows": rows,
        "row_count": len(rows),
    }
    return slim_make_list_payload(payload)


def _parse_pdf_make_list(uploaded_file, *, source_filename: str) -> dict:
    file_path = _resolve_path(uploaded_file)
    headers, records = parse_make_list_pdf(file_path)
    if not headers or not records:
        raise MakeListParseError(
            "Could not extract make-list rows from the PDF. "
            "Expected numbered lines with description and approved makes."
        )
    serial_key = detect_serial_key(headers)
    rows, column_roles = attach_approved_makes_list(
        attach_row_hierarchy(records, serial_key=serial_key),
        headers=headers,
    )
    payload = {
        "version": SCHEMA_VERSION,
        "format": "pdf",
        "source_filename": source_filename,
        "serial_key": serial_key,
        "headers": headers,
        "column_roles": column_roles,
        "rows": rows,
        "row_count": len(rows),
    }
    return slim_make_list_payload(payload)


def parse_make_list_file(uploaded_file, *, source_filename: str = "") -> dict:
    """Return normalized make-list JSON from Excel or PDF."""
    name = source_filename or Path(str(uploaded_file)).name
    lower_name = name.lower()
    if lower_name.endswith(".pdf"):
        payload = _parse_pdf_make_list(uploaded_file, source_filename=name)
    elif lower_name.endswith((".xlsx", ".xlsm")):
        payload = _parse_excel_make_list(uploaded_file, source_filename=name)
    else:
        raise MakeListParseError("Make list must be .xlsx, .xlsm, or .pdf")

    if not payload.get("row_count"):
        raise MakeListParseError(f"Make list '{name}' produced no data rows.")

    try:
        from apps.boq.services.make_list_category_mapping_service import (
            MakeListCategoryMappingService,
        )

        payload = MakeListCategoryMappingService().ensure_mappings(payload)
    except Exception:
        logger.exception("Make-list category mapping skipped for '%s'", name)

    logger.info(
        "Parsed make list '%s' (%s): %s rows from sheet(s) %s",
        name,
        payload["format"],
        payload["row_count"],
        payload.get("sheets") or ["?"],
    )
    return payload
