"""Group BOQ rows for analysis by serial lineage (parent + children as one section)."""
from __future__ import annotations

import re
from typing import Any

from apps.boq.services.boq_analysis_display_service import _field_from_map
from apps.boq.services.serial_normalizer import (
    analysis_fields,
    is_section_roman,
    letter_from_serial,
)

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
# Workbooks often store quantities in Total / floor columns instead of Qty.
_QTY_KEYS = ("qty", "quantity", "qnty", "nos", "total", "ground", "basement")
_UNIT_KEYS = ("unit", "uom")
_RATE_KEYS = ("rate", "unit_rate", "basic_rate")

_SPEC_QTY_LINE = re.compile(
    r"operating\s*temp|temp\.?\s*:|pressure\s*:|speed\s*:|head\s*:|flow\s*:|"
    r"voltage\s*:|rpm\s*:|capacity\s*:",
    re.IGNORECASE,
)
_RATE_ONLY = re.compile(r"^\s*rate\s*only\s*$", re.IGNORECASE)
_TOTAL_LABEL = re.compile(r"^\s*totals?\s*:?\s*$", re.IGNORECASE)


def qty_cell_status(fields: dict[str, Any]) -> tuple[str, Any, Any]:
    """
    Inspect Unit/Qty cells on a BOQ row.

    Returns ``(status, qty_value, unit)`` where status is:
    - ``empty`` — no qty cell filled
    - ``numeric`` — numeric qty (including values like ``10``)
    - ``zero`` — explicit 0 / 0.0
    - ``rate_only`` — Rate Only (priced later / rate column)
    """
    unit = _field_from_map(fields, _UNIT_KEYS)
    qty = _field_from_map(fields, _QTY_KEYS)
    if qty in (None, ""):
        return "empty", None, unit

    if isinstance(qty, (int, float)):
        if float(qty) == 0:
            return "zero", 0, unit
        return "numeric", qty, unit

    text = str(qty).strip()
    if not text:
        return "empty", None, unit
    if _RATE_ONLY.match(text):
        return "rate_only", "Rate Only", unit
    if text in {"0", "0.0", "0.00"}:
        return "zero", 0, unit
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        if re.search(r"\d", text):
            return "numeric", qty, unit
        return "rate_only", text, unit
    if number == 0:
        return "zero", 0, unit
    return "numeric", qty if "." in text or "e" in text.lower() else (int(number) if number.is_integer() else number), unit


def has_quantity(fields: dict[str, Any]) -> bool:
    """True when a Qty cell is filled (numeric, 0, or Rate Only)."""
    status, _qty, _unit = qty_cell_status(fields)
    return status != "empty"


def has_priced_quantity(fields: dict[str, Any]) -> bool:
    """True for numeric qty including zero (excludes Rate Only)."""
    status, _qty, _unit = qty_cell_status(fields)
    return status in {"numeric", "zero"}


def _is_structural_serial(serial: str) -> bool:
    return bool(re.match(r"^(\d+(?:\.\d+)*)$", str(serial).strip()))


def _is_letter_serial(serial: str) -> bool:
    """True for product letters: ``a``, ``(A)``, ``a)``."""
    return letter_from_serial(serial) is not None


def _is_spec_description(description: str) -> bool:
    return bool(_SPEC_QTY_LINE.search(description or ""))


def _is_section_title_row(row: dict[str, Any], fields: dict[str, Any]) -> bool:
    serial = str(row.get("serial") or "").strip()
    description = str(_field_from_map(fields, _DESCRIPTION_KEYS) or "").strip()
    if is_section_roman(serial):
        return True
    if _TOTAL_LABEL.match(description):
        return True
    if not serial and not description:
        return True
    return False


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
    Hierarchy helper for nested specs vs product/item nodes.

    Analysis extraction prefers ``grouped_anchor_rows`` serial-lineage sections.
    """
    fields = analysis_fields(row)
    if has_quantity(fields):
        return True
    if not row.get("parent_row_id"):
        return True
    serial = str(row.get("serial") or "").strip()
    if _is_structural_serial(serial) or is_section_roman(serial):
        return True
    description = str(_field_from_map(fields, _DESCRIPTION_KEYS) or "")
    if _is_spec_description(description):
        return False
    return _is_letter_serial(serial)


def _collect_descendant_ids(
    row_id: str,
    children: dict[str, list[str]],
    index: dict[str, dict[str, Any]],
) -> list[str]:
    """Descendants excluding nested product/item anchors (legacy nested-spec helper)."""
    ordered: list[str] = []
    stack = list(children.get(row_id, []))
    while stack:
        child_id = stack.pop(0)
        child_row = index.get(child_id)
        if child_row and is_anchor_row(child_row, children):
            continue
        ordered.append(child_id)
        stack[0:0] = children.get(child_id, [])
    return ordered


def _collect_all_descendant_ids(
    row_id: str,
    children: dict[str, list[str]],
) -> list[str]:
    """All descendants in document order (includes nested products such as 1.1 / 1.2)."""
    ordered: list[str] = []
    stack = list(children.get(row_id, []))
    while stack:
        child_id = stack.pop(0)
        ordered.append(child_id)
        stack[0:0] = children.get(child_id, [])
    return ordered


def _is_section_boundary_parent(
    row: dict[str, Any],
    index: dict[str, dict[str, Any]],
) -> bool:
    """True when this row sits directly under a chapter/section (or is top-level)."""
    parent_id = row.get("parent_row_id")
    if not parent_id:
        return True
    parent = index.get(str(parent_id))
    if not parent:
        return True
    return _is_section_title_row(parent, analysis_fields(parent))


def _is_lineage_section_root(
    row: dict[str, Any],
    *,
    index: dict[str, dict[str, Any]],
    children: dict[str, list[str]],
) -> bool:
    """
    Start of one Analysis section: item under a chapter that owns its serial subtree.

    Example: ``1`` (description) with children ``1.1`` / ``1.2`` → one section.
    ``1.1`` itself is not a root because its parent is ``1``, not a section boundary.
    """
    fields = analysis_fields(row)
    if _is_section_title_row(row, fields):
        return False
    if not _is_section_boundary_parent(row, index):
        return False

    row_id = str(row.get("row_id") or "")
    kids = children.get(row_id, [])
    serial = str(row.get("serial") or "").strip()
    description = row_description(row)

    if kids:
        return True
    if has_quantity(fields):
        return True
    if _is_letter_serial(serial) and description and not _is_spec_description(description):
        return True
    if _is_structural_serial(serial) and description:
        return True
    return False


def resolve_group_row_id(boq_data: dict[str, Any], row_id: str) -> str | None:
    """If ``row_id`` belongs to a lineage section, return that section's anchor id."""
    target = str(row_id)
    for group in grouped_anchor_rows(boq_data):
        anchor_id = str(group.get("row_id") or "")
        group_ids = [str(item) for item in (group.get("group_ids") or [])]
        if target == anchor_id or target in group_ids:
            return anchor_id or target
    return None


def resolve_quantity_block_row_id(boq_data: dict[str, Any], row_id: str) -> str | None:
    """Backward-compatible alias for ``resolve_group_row_id``."""
    return resolve_group_row_id(boq_data, row_id)


def resolve_anchor_row_id(boq_data: dict[str, Any], row_id: str) -> str:
    """Return lineage-section anchor when applicable, else nearest hierarchy anchor."""
    block_id = resolve_group_row_id(boq_data, row_id)
    if block_id:
        return block_id

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
    """Ancestors + anchor + all descendants (full serial lineage text)."""
    children = _children_map(rows)
    index = _row_index(rows)
    ancestors = get_ancestor_ids(anchor_row_id, index)
    descendants = _collect_all_descendant_ids(anchor_row_id, children)
    return [*ancestors, anchor_row_id, *descendants]


def group_ids_for_anchor(anchor_row_id: str, rows: list[dict[str, Any]]) -> list[str]:
    """Anchor + all descendants (product ownership / consolidate)."""
    children = _children_map(rows)
    descendants = _collect_all_descendant_ids(anchor_row_id, children)
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


def lineage_parts(index: dict[str, dict[str, Any]], row_ids: list[str]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for row_id in row_ids:
        row = index.get(row_id)
        if not row:
            continue
        text = row_description(row)
        fields = analysis_fields(row)
        status, qty, unit = qty_cell_status(fields)
        part: dict[str, Any] = {
            "row_id": row_id,
            "serial": str(row.get("serial") or ""),
            "description": text,
            "qty": qty,
            "unit": unit,
            "qty_status": status,
        }
        if status == "rate_only":
            part["boq_rate"] = _rate_from_fields(fields)
            part["rate_only"] = True
        parts.append(part)
    return parts


def _qty_unit_from_fields(fields: dict[str, Any]) -> tuple[Any, Any]:
    status, qty, unit = qty_cell_status(fields)
    if status == "empty":
        return None, unit
    return qty, unit


def _rate_from_fields(fields: dict[str, Any]) -> Any:
    return _field_from_map(fields, _RATE_KEYS)


def _qty_rows_in_lineage(
    index: dict[str, dict[str, Any]],
    row_ids: list[str],
) -> list[dict[str, Any]]:
    """Filled Unit/Qty rows inside a lineage section (where amounts belong)."""
    found: list[dict[str, Any]] = []
    for row_id in row_ids:
        row = index.get(row_id)
        if not row:
            continue
        fields = analysis_fields(row)
        status, qty, unit = qty_cell_status(fields)
        if status == "empty":
            continue
        found.append(
            {
                "row_id": row_id,
                "serial": str(row.get("serial") or ""),
                "description": row_description(row),
                "qty": qty,
                "unit": unit,
                "qty_status": status,
                "rate_only": status == "rate_only",
                "boq_rate": _rate_from_fields(fields) if status == "rate_only" else None,
            }
        )
    return found


def anchor_qty_unit(index: dict[str, dict[str, Any]], anchor_row_id: str) -> tuple[Any, Any]:
    """Prefer qty on the anchor; otherwise first descendant with a quantity cell."""
    row = index.get(anchor_row_id) or {}
    fields = analysis_fields(row)
    status, qty, unit = qty_cell_status(fields)
    if status != "empty":
        return qty, unit

    rows = list(index.values())
    for child_id in _collect_all_descendant_ids(anchor_row_id, _children_map(rows)):
        child = index.get(child_id) or {}
        child_status, child_qty, child_unit = qty_cell_status(analysis_fields(child))
        if child_status != "empty":
            return child_qty, child_unit or unit
    return qty, unit


def full_description_for_row(boq_data: dict[str, Any], row_id: str) -> str:
    rows = boq_data.get("rows") or []
    if not rows:
        return ""
    index = _row_index(rows)
    if row_id not in index:
        return ""
    group_id = resolve_group_row_id(boq_data, row_id) or row_id
    lineage_ids = lineage_ids_for_anchor(group_id, rows)
    return combine_row_descriptions(index, lineage_ids)


def _emit_lineage_section(
    *,
    root: dict[str, Any],
    rows: list[dict[str, Any]],
    index: dict[str, dict[str, Any]],
    children: dict[str, list[str]],
) -> dict[str, Any]:
    root_id = str(root.get("row_id"))
    group_ids = group_ids_for_anchor(root_id, rows)
    # Ancestors (e.g. chapter title) for text only — ownership stays on group_ids.
    ancestor_ids = [
        ancestor_id
        for ancestor_id in get_ancestor_ids(root_id, index)
        if ancestor_id not in group_ids
    ]
    lineage_ids = [*ancestor_ids, *group_ids]
    qty_rows = _qty_rows_in_lineage(index, group_ids)

    qty = None
    unit = None
    qty_status = "empty"
    rate_only = False
    boq_rate = None
    qty_row_id = ""
    if len(qty_rows) == 1:
        only = qty_rows[0]
        qty = only["qty"]
        unit = only["unit"]
        qty_status = only["qty_status"]
        rate_only = bool(only.get("rate_only"))
        boq_rate = only.get("boq_rate")
        qty_row_id = only["row_id"]
    elif len(qty_rows) > 1:
        qty_status = "multi"

    return {
        "row_id": root_id,
        "serial": root.get("serial", ""),
        "depth": root.get("depth", 0),
        "lineage_ids": lineage_ids,
        "group_ids": group_ids,
        "lineage_count": len(lineage_ids),
        "description": row_description(root),
        "full_description": combine_row_descriptions(index, lineage_ids),
        "lineage_parts": lineage_parts(index, lineage_ids),
        "qty": qty,
        "unit": unit,
        "qty_status": qty_status,
        "rate_only": rate_only,
        "boq_rate": boq_rate,
        "qty_row_id": qty_row_id,
        "qty_rows": qty_rows,
        "has_children": len(group_ids) > 1,
    }


def grouped_anchor_rows(boq_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return extractable sections keyed by serial lineage.

    One Analysis section = an item that sits under a chapter/section boundary
    (for example ``1``) plus its full serial subtree (``1.1``, ``1.2``, specs…).
    Shared parent description is kept with every child product in that section.
    Filled Unit/Qty rows inside the subtree still carry amounts (including ``0``
    and ``Rate Only``); they do not split the lineage into separate sections.
    """
    rows = boq_data.get("rows") or []
    if not rows:
        return []

    index = _row_index(rows)
    children = _children_map(rows)
    covered: set[str] = set()
    grouped: list[dict[str, Any]] = []

    for row in rows:
        row_id = str(row.get("row_id") or "")
        if not row_id or row_id in covered:
            continue
        if not _is_lineage_section_root(row, index=index, children=children):
            continue

        section = _emit_lineage_section(
            root=row,
            rows=rows,
            index=index,
            children=children,
        )
        grouped.append(section)
        covered.update(str(item) for item in section.get("group_ids") or [])

    return grouped
