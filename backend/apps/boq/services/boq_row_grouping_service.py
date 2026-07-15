"""Group BOQ rows by serial lineage for analysis display and matching."""
from __future__ import annotations

from typing import Any

from apps.boq.services.boq_analysis_display_service import _field_from_map
from apps.boq.services.serial_normalizer import analysis_fields

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_UNIT_KEYS = ("unit", "uom")


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


def _collect_descendant_ids(row_id: str, children: dict[str, list[str]]) -> list[str]:
    ordered: list[str] = []
    stack = list(children.get(row_id, []))
    while stack:
        child_id = stack.pop(0)
        ordered.append(child_id)
        stack[0:0] = children.get(child_id, [])
    return ordered


def is_anchor_row(row: dict[str, Any]) -> bool:
    return not row.get("parent_row_id")


def resolve_anchor_row_id(boq_data: dict[str, Any], row_id: str) -> str:
    """Return the anchor row_id for a lineage node (or the id itself if already an anchor)."""
    rows = boq_data.get("rows") or []
    index = _row_index(rows)
    current_id = str(row_id)
    row = index.get(current_id)
    if not row:
        return current_id
    while row.get("parent_row_id"):
        parent_id = str(row.get("parent_row_id"))
        parent = index.get(parent_id)
        if not parent:
            break
        current_id = parent_id
        row = parent
    return current_id


def lineage_ids_for_anchor(anchor_row_id: str, rows: list[dict[str, Any]]) -> list[str]:
    children = _children_map(rows)
    return [anchor_row_id, *_collect_descendant_ids(anchor_row_id, children)]


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


def anchor_qty_unit(index: dict[str, dict[str, Any]], anchor_row_id: str) -> tuple[Any, Any]:
    row = index.get(anchor_row_id) or {}
    fields = analysis_fields(row)
    return _field_from_map(fields, _QTY_KEYS), _field_from_map(fields, _UNIT_KEYS)


def full_description_for_row(boq_data: dict[str, Any], row_id: str) -> str:
    rows = boq_data.get("rows") or []
    if not rows:
        return ""
    index = _row_index(rows)
    if row_id not in index:
        return ""
    lineage_ids = lineage_ids_for_anchor(row_id, rows) if is_anchor_row(index[row_id]) else [row_id]
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
        if not row_id or not is_anchor_row(row):
            continue
        lineage_ids = lineage_ids_for_anchor(row_id, rows)
        qty, unit = anchor_qty_unit(index, row_id)
        grouped.append(
            {
                "row_id": row_id,
                "serial": row.get("serial", ""),
                "depth": row.get("depth", 0),
                "lineage_ids": lineage_ids,
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
