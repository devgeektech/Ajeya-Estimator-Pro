"""Database workbook validation service.

Validates the structure of an uploaded master workbook before import
(docs/PROJECT_STRUCTURE.md - database_manager/services/validator.py).
"""
from __future__ import annotations

from pathlib import Path

from common.constants import MASTER_SHEETS
from common.exceptions import ValidationError
from utils.excel import list_sheet_names


def validate_workbook(file_path: str | Path) -> list[str]:
    """Ensure all required master sheets are present.

    Returns the list of sheet names on success; raises ValidationError if
    any required sheet is missing.
    """
    sheet_names = list_sheet_names(file_path)
    missing = [s for s in MASTER_SHEETS if s not in sheet_names]
    if missing:
        raise ValidationError(
            "Workbook is missing required sheets: " + ", ".join(missing)
        )
    return sheet_names
