"""Excel helpers built on pandas / openpyxl.

Used by the database import and export layers. Kept dependency-light and
side-effect free so it can be unit tested in isolation.
"""
from __future__ import annotations

from datetime import date, datetime
import re
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook


def read_sheets(file_path: str | Path) -> dict[str, "object"]:
    """Read all sheets of a workbook into a mapping of {sheet_name: DataFrame}.

    Returns all sheets using pandas.
    """
    return pd.read_excel(file_path, sheet_name=None)


def list_sheet_names(file_path: str | Path) -> list[str]:
    """Return the sheet names present in a workbook."""
    workbook = load_workbook(filename=file_path, read_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def _normalize_header(value) -> str:
    """Normalize a header cell to a comparable key (lower snake_case)."""
    if value is None:
        return ""
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", str(value).strip().lower())
    return normalized.strip("_")


def _display_value(value):
    """Return a stable display value for JSON/UI preservation."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return format(value, ".15g")
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _dedupe_headers(headers: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    deduped: list[dict] = []
    for header in headers:
        key = header["key"]
        seen[key] = seen.get(key, 0) + 1
        unique_key = key if seen[key] == 1 else f"{key}_{seen[key]}"
        deduped.append({**header, "key": unique_key})
    return deduped


def _headers_from_cells(cells) -> list[dict]:
    headers = []
    for idx, cell in enumerate(cells):
        key = _normalize_header(cell.value)
        if key:
            headers.append({"key": key, "label": str(cell.value).strip(), "index": idx})
    return _dedupe_headers(headers)


def _header_score(headers: list[dict], header_keys: set[str] | None) -> tuple[int, int]:
    if not header_keys:
        return (0, len(headers))
    matches = sum(1 for header in headers if header["key"] in header_keys)
    return (matches, len(headers))


def _select_header_row(non_empty_rows, header_keys: set[str] | None):
    if not non_empty_rows:
        return None
    if not header_keys:
        row_number, cells = non_empty_rows[0]
        return row_number, cells, _headers_from_cells(cells)
    candidates = [
        (row_number, cells, _headers_from_cells(cells))
        for row_number, cells in non_empty_rows[:25]
    ]
    best = max(candidates, key=lambda candidate: _header_score(candidate[2], header_keys))
    if _header_score(best[2], header_keys)[0] > 0:
        return best
    row_number, cells = non_empty_rows[0]
    return row_number, cells, _headers_from_cells(cells)


def read_rows_with_metadata(
    file_path: str | Path,
    sheet_name: str | None = None,
    header_keys: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Read rows with original header labels and worksheet row numbers.

    Returns ``(headers, records)`` where headers are ``{key, label}`` dicts and
    records include raw ``values``, ``display_values`` and ``excel_row_number``.
    Fully empty rows are skipped, but blank cells inside captured rows are
    preserved.
    """
    workbook = load_workbook(filename=file_path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet_name] if sheet_name else workbook.active
        non_empty_rows = [
            (row_number, cells)
            for row_number, cells in enumerate(worksheet.iter_rows(), start=1)
            if cells and any(cell.value is not None for cell in cells)
        ]
        selected = _select_header_row(non_empty_rows, header_keys)
        if not selected:
            return [], []
        header_row_number, _, headers = selected

        records: list[dict] = []
        for row_number, cells in non_empty_rows:
            if row_number <= header_row_number:
                continue
            values = {
                header["key"]: cells[header["index"]].value
                if header["index"] < len(cells) else None
                for header in headers
            }
            display_values = {
                header["key"]: _display_value(cells[header["index"]].value)
                if header["index"] < len(cells) else None
                for header in headers
            }
            records.append(
                {
                    "excel_row_number": row_number,
                    "values": values,
                    "display_values": display_values,
                }
            )
        return headers, records
    finally:
        workbook.close()


def read_rows(file_path: str | Path, sheet_name: str | None = None) -> list[dict]:
    """Read a worksheet into a list of {normalized_header: value} dicts.

    The first non-empty row is treated as the header. Fully empty rows are
    skipped. When ``sheet_name`` is None the active (first) worksheet is used.
    Uses openpyxl only (no pandas) so it installs cleanly everywhere.
    """
    _, records = read_rows_with_metadata(file_path, sheet_name=sheet_name)
    return [record["values"] for record in records]
