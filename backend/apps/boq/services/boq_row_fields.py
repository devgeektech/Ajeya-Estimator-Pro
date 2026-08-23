"""Shared BOQ workbook field keys and tiny value helpers.

Display, matching, labour, and export all read the same description / qty / unit
columns. Grouping may extend ``QTY_KEYS`` with floor/total columns. Make-list
constraint may extend ``DESCRIPTION_KEYS`` with material labels. Matching
``normalize_text`` only collapses whitespace — make-list brand matching keeps
its own alphanumeric normalizer.
"""
from __future__ import annotations

import re
from typing import Any

DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
QTY_KEYS = ("qty", "quantity", "qnty", "nos", "total", "ground", "basement")
UNIT_KEYS = ("unit", "uom")


def field_from_map(fields: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return value
    return None


def is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def is_blank(value: Any) -> bool:
    return not is_filled(value)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def is_job_unit(unit: Any) -> bool:
    """Return True if unit string represents 'job' (activity only)."""
    if unit is None:
        return False
    val = normalize_text(unit)
    if not val:
        return False
    return val == "job" or val == "jobs" or val.startswith("job.") or val.startswith("job ") or val == "job activity"


def ordered_boq_rows(boq_data: dict) -> list[dict[str, Any]]:
    """Return BOQ rows in workbook order; fall back to ``rows_tree`` when flat rows are missing."""
    flat_rows = boq_data.get("rows") or []
    if flat_rows:
        return list(flat_rows)
    from apps.boq.services.make_list_constraint_service import walk_rows_tree

    return walk_rows_tree(boq_data.get("rows_tree") or [])

