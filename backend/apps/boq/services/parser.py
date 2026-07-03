"""BOQ and make-list parsing.

BOQ workbooks arrive in varying client formats, so header matching is tolerant
and falls back gracefully (docs/PRD.md - Product Matching Rules: understand
varying descriptions). Parsing only captures the original rows; AI
understanding and matching happen in later phases.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from utils.excel import read_rows

# Accepted header aliases (already normalized to lower snake_case).
DESCRIPTION_KEYS = (
    "description", "item_description", "item", "particulars",
    "work_description", "scope", "description_of_work",
)
QUANTITY_KEYS = ("quantity", "qty", "nos")
UNIT_KEYS = ("unit", "uom", "units")

MAKE_KEYS = ("make", "approved_make", "brand", "manufacturer", "makes")
CATEGORY_KEYS = ("category", "item_category", "type", "section")


def _pick(row: dict, keys) -> object:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _to_decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_boq_items(file_path: str) -> list[dict]:
    """Return a list of {row_number, description, quantity, unit} dicts."""
    rows = read_rows(file_path)
    items: list[dict] = []
    row_number = 0
    for row in rows:
        description = _pick(row, DESCRIPTION_KEYS)
        if description in (None, ""):
            continue
        row_number += 1
        items.append(
            {
                "row_number": row_number,
                "description": str(description).strip(),
                "quantity": _to_decimal(_pick(row, QUANTITY_KEYS)),
                "unit": (str(_pick(row, UNIT_KEYS)).strip() if _pick(row, UNIT_KEYS) else ""),
            }
        )
    return items


def parse_make_list(file_path: str) -> list[dict]:
    """Return a list of {make, category} dicts from a make-list workbook."""
    rows = read_rows(file_path)
    entries: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        make = _pick(row, MAKE_KEYS)
        if make in (None, ""):
            continue
        make = str(make).strip()
        if make.lower() in seen:
            continue
        seen.add(make.lower())
        category = _pick(row, CATEGORY_KEYS)
        entries.append(
            {"make": make, "category": str(category).strip() if category else ""}
        )
    return entries
