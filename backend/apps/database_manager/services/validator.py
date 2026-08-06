"""Database workbook validation service.

Validates the structure of an uploaded master workbook before import.
"""
from __future__ import annotations

from pathlib import Path

from common.constants import (
    MASTER_SHEET_ALIASES,
    OPTIONAL_MASTER_SHEETS,
    REQUIRED_MASTER_SHEETS,
)
from common.exceptions import ValidationError
from utils.excel import list_sheet_names


def resolve_master_sheet_name(sheet_names: list[str] | set[str], preferred: str) -> str | None:
    """Return the workbook sheet title that matches a required master sheet."""
    available = set(sheet_names)
    lower_map = {name.lower(): name for name in available}
    for alias in MASTER_SHEET_ALIASES.get(preferred, (preferred,)):
        if alias in available:
            return alias
        matched = lower_map.get(alias.lower())
        if matched:
            return matched
    return None


def validate_workbook(file_path: str | Path) -> list[str]:
    """Ensure required master sheets are present.

    Optional sheets (labour, TOR, state control) may be omitted entirely;
    the importer skips any sheet that is not in the workbook.

    Returns the list of sheet names on success; raises ValidationError if
    any required sheet is missing.
    """
    sheet_names = list_sheet_names(file_path)
    missing_required = [
        preferred
        for preferred in REQUIRED_MASTER_SHEETS
        if resolve_master_sheet_name(sheet_names, preferred) is None
    ]
    if missing_required:
        raise ValidationError(
            "Workbook is missing required sheets: " + ", ".join(missing_required)
        )
    return sheet_names


def missing_optional_sheets(file_path: str | Path) -> list[str]:
    """Return optional master sheet names that are not in the workbook."""
    sheet_names = set(list_sheet_names(file_path))
    return [sheet for sheet in OPTIONAL_MASTER_SHEETS if sheet not in sheet_names]
