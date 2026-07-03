"""Excel helpers built on pandas / openpyxl.

Used by the database import and export layers. Kept dependency-light and
side-effect free so it can be unit tested in isolation.
"""
from __future__ import annotations

from pathlib import Path


def read_sheets(file_path: str | Path) -> dict[str, "object"]:
    """Read all sheets of a workbook into a mapping of {sheet_name: DataFrame}.

    Imported lazily so the project does not require pandas to be installed
    for parts of the app that don't touch Excel.
    """
    import pandas as pd

    return pd.read_excel(file_path, sheet_name=None)


def list_sheet_names(file_path: str | Path) -> list[str]:
    """Return the sheet names present in a workbook."""
    from openpyxl import load_workbook

    workbook = load_workbook(filename=file_path, read_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def _normalize_header(value) -> str:
    """Normalize a header cell to a comparable key (lower snake_case)."""
    if value is None:
        return ""
    return str(value).strip().lower().replace(" ", "_")


def read_rows(file_path: str | Path, sheet_name: str | None = None) -> list[dict]:
    """Read a worksheet into a list of {normalized_header: value} dicts.

    The first non-empty row is treated as the header. Fully empty rows are
    skipped. When ``sheet_name`` is None the active (first) worksheet is used.
    Uses openpyxl only (no pandas) so it installs cleanly everywhere.
    """
    from openpyxl import load_workbook

    workbook = load_workbook(filename=file_path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet_name] if sheet_name else workbook.active
        rows_iter = worksheet.iter_rows(values_only=True)
        headers: list[str] = []
        for raw in rows_iter:
            if raw and any(cell is not None for cell in raw):
                headers = [_normalize_header(cell) for cell in raw]
                break

        records: list[dict] = []
        for raw in rows_iter:
            if not raw or all(cell is None for cell in raw):
                continue
            record = {
                header: raw[idx] if idx < len(raw) else None
                for idx, header in enumerate(headers)
                if header
            }
            records.append(record)
        return records
    finally:
        workbook.close()
