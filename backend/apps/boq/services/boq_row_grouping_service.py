"""Group BOQ rows by serial lineage for analysis display and matching."""
from __future__ import annotations

import re
from typing import Any

from apps.boq.services.boq_analysis_display_service import _field_from_map
from apps.boq.services.serial_normalizer import analysis_fields

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
# Workbooks often store quantities in Total / floor columns instead of Qty.
_QTY_KEYS = ("qty", "quantity", "qnty", "nos", "total", "ground", "basement")
_UNIT_KEYS = ("unit", "uom")

_LETTER_SERIAL = re.compile(r"^[a-zA-Z]$")
_SPEC_QTY_LINE = re.compile(
    r"operating\s*temp|temp\.?\s*:|pressure\s*:|speed\s*:|head\s*:|flow\s*:|"
    r"voltage\s*:|rpm\s*:|capacity\s*:",
    re.IGNORECASE,
)


def has_quantity(fields: dict[str, Any]) -> bool:
    for key in _QTY_KEYS:
        value = fields.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)) and value != 0:
            return True
        text = str(value).strip()
        if text and text not in {"0", "0.0"}:
            return re.search(r"\d", text) is not None
    return False


def _is_structural_serial(serial: str) -> bool:
    return bool(re.match(r"^(\d+(?:\.\d+)*)$", str(serial).strip()))


def _is_letter_serial(serial: str) -> bool:
    return bool(_LETTER_SERIAL.match(str(serial or "").strip()))


def _row_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("row_id")): row for row in rows if row.get("row_id")}


def _children_map(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for row in rows:
        parent_id = row.get("parent_row_id")
        row_id = row.get("row_id")
        if not parent_id or not row_id:
            continue
        mapping.setdefault(str(parent_id), []).append(str(row_id))
    return mapping


def is_anchor_row(row: dict[str, Any], children_map: dict[str, list[str]] | None = None) -> bool:
    """
    Anchor rows are extractable product groups.

    - Root / structural serials (1, 1.1, 2.3) are always anchors.
    - Lettered priced lines (a, b, c…) with quantity are anchors, unless they are
      obvious spec carriers (Operating Temp, etc.) that belong under a parent item.
    - Lettered lines that already have non-anchor children (specs) are anchors even
      without quantity, so products stay attached to the lettered parent.
    """
    if not row.get("parent_row_id"):
        return True
    serial = str(row.get("serial") or "").strip()
    if _is_structural_serial(serial):
        return True
    fields = analysis_fields(row)
    description = str(_field_from_map(fields, _DESCRIPTION_KEYS) or "")
    if _SPEC_QTY_LINE.search(description):
        return False

    row_id = str(row.get("row_id") or "")
    child_ids = (children_map or {}).get(row_id) or []
    if _is_letter_serial(serial) and child_ids:
        # Has nested spec/continuation children → treat as product group anchor.
        return True

    if not (has_quantity(fields) and _is_letter_serial(serial)):
        return False
    return True


def _collect_descendant_ids(
    row_id: str,
    children: dict[str, list[str]],
    index: dict[str, dict[str, Any]],
) -> list[str]:
    ordered: list[str] = []
    stack = list(children.get(row_id, []))
    while stack:
        child_id = stack.pop(0)
        child_row = index.get(child_id)
        # Stop at nested anchors so each product group stays isolated.
        if child_row and is_anchor_row(child_row, children):
            continue
        ordered.append(child_id)
        stack[0:0] = children.get(child_id, [])
    return ordered


def resolve_anchor_row_id(boq_data: dict[str, Any], row_id: str) -> str:
    """Return nearest anchor for a node (self if already an anchor)."""
    rows = boq_data.get("rows") or []
    index = _row_index(rows)
    children = _children_map(rows)
    current_id = str(row_id)
    row = index.get(current_id)
    if not row:
        return current_id
    if is_anchor_row(row, children):
        return current_id
    while row.get("parent_row_id"):
        parent_id = str(row.get("parent_row_id"))
        parent = index.get(parent_id)
        if not parent:
            break
        current_id = parent_id
        row = parent
        if is_anchor_row(row, children):
            return current_id
    return current_id


def get_ancestor_ids(row_id: str, index: dict[str, dict[str, Any]]) -> list[str]:
    ancestors = []
    current_id = row_id
    while True:
        row = index.get(current_id)
        if not row:
            break
        parent_id = str(row.get("parent_row_id") or "")
        if not parent_id:
            break
        ancestors.insert(0, parent_id)
        current_id = parent_id
    return ancestors


def lineage_ids_for_anchor(anchor_row_id: str, rows: list[dict[str, Any]]) -> list[str]:
    """Ancestors + anchor + descendants (for description context)."""
    children = _children_map(rows)
    index = _row_index(rows)
    ancestors = get_ancestor_ids(anchor_row_id, index)
    descendants = _collect_descendant_ids(anchor_row_id, children, index)
    return [*ancestors, anchor_row_id, *descendants]


def group_ids_for_anchor(anchor_row_id: str, rows: list[dict[str, Any]]) -> list[str]:
    """Anchor + descendants only (for product ownership / consolidate)."""
    children = _children_map(rows)
    index = _row_index(rows)
    descendants = _collect_descendant_ids(anchor_row_id, children, index)
    return [anchor_row_id, *descendants]


def row_description(row: dict[str, Any]) -> str:
    fields = analysis_fields(row)
    return str(_field_from_map(fields, _DESCRIPTION_KEYS) or "").strip()


def combine_row_descriptions(index: dict[str, dict[str, Any]], row_ids: list[str]) -> str:
    parts: list[str] = []
    for row_id in row_ids:
        row = index.get(row_id)
        if not row:
            continue
        text = row_description(row)
        if text:
            parts.append(text)
    return " ".join(parts)


def lineage_parts(index: dict[str, dict[str, Any]], row_ids: list[str]) -> list[dict[str, str]]:
    parts: list[dict[str, str]] = []
    for row_id in row_ids:
        row = index.get(row_id)
        if not row:
            continue
        text = row_description(row)
        if not text:
            continue
        parts.append(
            {
                "row_id": row_id,
                "serial": str(row.get("serial") or ""),
                "description": text,
            }
        )
    return parts


def _qty_unit_from_fields(fields: dict[str, Any]) -> tuple[Any, Any]:
    return _field_from_map(fields, _QTY_KEYS), _field_from_map(fields, _UNIT_KEYS)


def anchor_qty_unit(index: dict[str, dict[str, Any]], anchor_row_id: str) -> tuple[Any, Any]:
    """Prefer qty on the anchor; otherwise first descendant with a quantity."""
    row = index.get(anchor_row_id) or {}
    qty, unit = _qty_unit_from_fields(analysis_fields(row))
    if qty not in (None, ""):
        return qty, unit

    rows = list(index.values())
    for child_id in _collect_descendant_ids(anchor_row_id, _children_map(rows), index):
        child = index.get(child_id) or {}
        child_qty, child_unit = _qty_unit_from_fields(analysis_fields(child))
        if child_qty not in (None, ""):
            return child_qty, child_unit or unit
    return qty, unit


def full_description_for_row(boq_data: dict[str, Any], row_id: str) -> str:
    rows = boq_data.get("rows") or []
    if not rows:
        return ""
    index = _row_index(rows)
    if row_id not in index:
        return ""

    children_map = _children_map(rows)
    is_anchor = is_anchor_row(index[row_id], children_map)
    lineage_ids = lineage_ids_for_anchor(row_id, rows) if is_anchor else [row_id]
    return combine_row_descriptions(index, lineage_ids)


def grouped_anchor_rows(boq_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return anchor rows with lineage metadata for the Analysis tab."""
    rows = boq_data.get("rows") or []
    if not rows:
        return []

    index = _row_index(rows)
    children = _children_map(rows)
    grouped: list[dict[str, Any]] = []

    for row in rows:
        row_id = str(row.get("row_id") or "")
        if not row_id or not is_anchor_row(row, children):
            continue
        lineage_ids = lineage_ids_for_anchor(row_id, rows)
        group_ids = group_ids_for_anchor(row_id, rows)
        descendants = group_ids[1:]
        qty, unit = anchor_qty_unit(index, row_id)
        grouped.append(
            {
                "row_id": row_id,
                "serial": row.get("serial", ""),
                "depth": row.get("depth", 0),
                "lineage_ids": lineage_ids,
                "group_ids": group_ids,
                "lineage_count": len(lineage_ids),
                "description": row_description(row),
                "full_description": combine_row_descriptions(index, lineage_ids),
                "lineage_parts": lineage_parts(index, lineage_ids),
                "qty": qty,
                "unit": unit,
                "has_children": bool(children.get(row_id)),
            }
        )
    return grouped
