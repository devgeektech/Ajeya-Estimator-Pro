"""Group BOQ rows for analysis by serial lineage (parent + children as one section).

Small related clusters stay together. Oversized chapter trees (e.g. ``2`` with
dozens of ``2.1`` / ``2.2`` product packages) are split so each package is
extracted separately while shared ancestor text remains on the lineage.
"""
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

# Soft budgets for one AI extract group. Exceeding any triggers a split when
# the group has structural (1.1 / 2.1) or lettered product children.
MAX_LINEAGE_LINES = 18
MAX_QTY_ROWS = 10
MAX_GROUP_CHARS = 10000

_SPEC_QTY_LINE = re.compile(
    r"operating\s*temp|temp\.?\s*:|pressure\s*:|speed\s*:|head\s*:|flow\s*:|"
    r"voltage\s*:|rpm\s*:|capacity\s*:",
    re.IGNORECASE,
)
_RATE_ONLY = re.compile(
    r"^\s*(rate\s*only|r\.?\s*o\.?|ro)\s*$",
    re.IGNORECASE,
)
_TOTAL_LABEL = re.compile(r"^\s*totals?\s*:?\s*$", re.IGNORECASE)
_STRUCTURAL_SERIAL = re.compile(r"^(\d+(?:\.\d+)*)$")
_DOTTED_STRUCTURAL = re.compile(r"^(\d+(?:\.\d+)+)$")
# Letter/size row text → size_hint for AI + deterministic binding.
_SIZE_HINT_FROM_TEXT = re.compile(
    r"(?i)(?:^|[^0-9])(\d+(?:\.\d+)?)\s*(?:mm|nb|inch|in|cm)?\b"
)


def _parse_size_hint_from_description(text: Any) -> tuple[str | None, str | None]:
    """Return (size_hint, unit) from a slot description like ``200mm dia``."""
    blob = str(text or "").strip()
    if not blob:
        return None, None
    match = _SIZE_HINT_FROM_TEXT.search(blob)
    if not match:
        return None, None
    size = match.group(1)
    try:
        number = float(size)
        if number.is_integer():
            size = str(int(number))
    except ValueError:
        pass
    unit = None
    if re.search(r"(?i)\bmm\b", blob):
        unit = "mm"
    elif re.search(r"(?i)\bnb\b", blob):
        unit = "NB"
    return size, unit


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
    return bool(_STRUCTURAL_SERIAL.match(str(serial).strip()))


def _is_dotted_structural_serial(serial: str) -> bool:
    """True for ``1.1``, ``2.15`` — not bare chapter ``1`` / ``2``."""
    return bool(_DOTTED_STRUCTURAL.match(str(serial).strip()))


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


def build_slots_for_section(
    index: dict[str, dict[str, Any]],
    owned_ids: list[str],
    qty_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    One product slot per filled Unit/Qty row.

    Context rows between the previous slot and this qty row are bound as local
    evidence (specs, letter headers, size lines). Shared section text stays on
    the section ``lineage_parts`` / ``full_description``.
    """
    if not qty_rows:
        return []

    qty_id_set = {str(item.get("row_id") or "") for item in qty_rows}
    owned = [str(item) for item in owned_ids]
    slots: list[dict[str, Any]] = []
    cursor = 0

    for slot_index, qty_row in enumerate(qty_rows):
        qty_row_id = str(qty_row.get("row_id") or "")
        try:
            qty_pos = owned.index(qty_row_id)
        except ValueError:
            qty_pos = cursor

        local_ids: list[str] = []
        for row_id in owned[cursor : qty_pos + 1]:
            if row_id == qty_row_id:
                continue
            if row_id in qty_id_set:
                continue
            local_ids.append(row_id)

        evidence_ids = [*local_ids, qty_row_id] if qty_row_id else list(local_ids)
        description = qty_row.get("description") or ""
        size_hint, _size_unit = _parse_size_hint_from_description(description)
        slots.append(
            {
                "slot_index": slot_index,
                "slot_id": f"{qty_row_id or 'slot'}:{slot_index}",
                "qty_row_id": qty_row_id,
                "serial": qty_row.get("serial") or "",
                "description": description,
                "size_hint": size_hint,
                "qty": qty_row.get("qty"),
                "unit": qty_row.get("unit"),
                "qty_status": qty_row.get("qty_status"),
                "rate_only": bool(qty_row.get("rate_only")),
                "boq_rate": qty_row.get("boq_rate"),
                "context_row_ids": local_ids,
                "evidence_text": combine_row_descriptions(index, evidence_ids),
            }
        )
        cursor = qty_pos + 1

    return slots


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
    group_ids: list[str] | None = None,
) -> dict[str, Any]:
    root_id = str(root.get("row_id"))
    owned_ids = list(group_ids) if group_ids is not None else group_ids_for_anchor(root_id, rows)
    if root_id not in owned_ids:
        owned_ids = [root_id, *[item for item in owned_ids if item != root_id]]
    # Ancestors (e.g. chapter title) for text only — ownership stays on group_ids.
    ancestor_ids = [
        ancestor_id
        for ancestor_id in get_ancestor_ids(root_id, index)
        if ancestor_id not in owned_ids
    ]
    lineage_ids = [*ancestor_ids, *owned_ids]
    qty_rows = _qty_rows_in_lineage(index, owned_ids)
    slots = build_slots_for_section(index, owned_ids, qty_rows)

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
        # Header shows the first Unit/Qty slot; products bind to their own slots.
        first = qty_rows[0]
        qty = first["qty"]
        unit = first["unit"]
        qty_status = "multi"
        rate_only = bool(first.get("rate_only"))
        boq_rate = first.get("boq_rate")
        qty_row_id = first["row_id"]

    return {
        "row_id": root_id,
        "serial": root.get("serial", ""),
        "depth": root.get("depth", 0),
        "lineage_ids": lineage_ids,
        "group_ids": owned_ids,
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
        "slots": slots,
        "slot_count": len(slots),
        "has_children": len(owned_ids) > 1,
    }


def _group_exceeds_budget(section: dict[str, Any]) -> bool:
    """
    Oversized multi-product trees may split at structural/lettered children.

    Single Unit/Qty packages (e.g. BOQ_2 ``1.04`` panel) must stay one section —
    blank detail rows are evidence, not separate products.
    """
    qty_count = len(section.get("qty_rows") or [])
    if qty_count <= 1:
        return False

    lines = int(section.get("lineage_count") or len(section.get("group_ids") or []))
    chars = len(str(section.get("full_description") or ""))
    return (
        lines > MAX_LINEAGE_LINES
        or qty_count > MAX_QTY_ROWS
        or chars > MAX_GROUP_CHARS
    )


def _is_letter_product_child(row: dict[str, Any]) -> bool:
    serial = str(row.get("serial") or "").strip()
    description = row_description(row)
    if not _is_letter_serial(serial):
        return False
    if not description or _is_spec_description(description):
        return False
    return True


def _is_plain_product_child(row: dict[str, Any]) -> bool:
    """Blank-serial / free-text child that still names a distinct supply item."""
    serial = str(row.get("serial") or "").strip()
    if serial and (_is_structural_serial(serial) or _is_letter_serial(serial)):
        return False
    description = row_description(row)
    if not description or _is_spec_description(description):
        return False
    if _TOTAL_LABEL.match(description):
        return False
    # Short section headers like INCOMING / BUSBARS stay with the panel package
    # unless they look like a full supply sentence.
    if len(description) < 28 and " " not in description.strip():
        return False
    return True


def _split_child_candidates(
    root_id: str,
    *,
    index: dict[str, dict[str, Any]],
    children: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """
    Prefer dotted structural packages (1.1 / 2.1); else lettered supply items.

    Do not split on blank-serial plain text children — those are package details
    (panel incomings/outgoings) that belong with the parent section.
    """
    direct = [index[cid] for cid in children.get(root_id, []) if cid in index]
    structural = [
        row
        for row in direct
        if _is_dotted_structural_serial(str(row.get("serial") or ""))
    ]
    if structural:
        return structural
    lettered = [row for row in direct if _is_letter_product_child(row)]
    if lettered:
        return lettered
    return []


def _residual_group_ids(
    root_id: str,
    *,
    children: dict[str, list[str]],
    covered: set[str],
) -> list[str]:
    """Root + descendants not already owned by a split child section."""
    residual = [root_id]
    for descendant_id in _collect_all_descendant_ids(root_id, children):
        if descendant_id not in covered:
            residual.append(descendant_id)
    return residual


def _residual_worth_extracting(
    section: dict[str, Any],
    *,
    index: dict[str, dict[str, Any]],
) -> bool:
    """Keep residuals that still carry qty or distinct product text beyond a title."""
    if section.get("qty_rows"):
        return True
    owned = [str(item) for item in (section.get("group_ids") or [])]
    if len(owned) <= 1:
        return False
    root_id = str(section.get("row_id") or "")
    root_desc = row_description(index.get(root_id) or {})
    for row_id in owned:
        if row_id == root_id:
            continue
        text = row_description(index.get(row_id) or {})
        if text and text != root_desc:
            return True
    return False


def grouped_anchor_rows(boq_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return extractable sections keyed by serial lineage.

    Default: an item under a chapter/section boundary (for example ``1``) plus its
    subtree stays one section so shared parent text applies to every product.

    Oversized trees (too many lines / qty rows / characters) are split at dotted
    children (``1.1``, ``2.1``, …) and recursively when those packages are still
    large. Shared ancestor text remains on each split section via ``lineage_ids``.
    """
    rows = boq_data.get("rows") or []
    if not rows:
        return []

    index = _row_index(rows)
    children = _children_map(rows)
    covered: set[str] = set()
    grouped: list[dict[str, Any]] = []

    def emit_or_split(root: dict[str, Any]) -> None:
        root_id = str(root.get("row_id") or "")
        if not root_id or root_id in covered:
            return

        section = _emit_lineage_section(
            root=root,
            rows=rows,
            index=index,
            children=children,
        )
        if not _group_exceeds_budget(section):
            grouped.append(section)
            covered.update(str(item) for item in section.get("group_ids") or [])
            return

        split_children = _split_child_candidates(
            root_id,
            index=index,
            children=children,
        )
        if not split_children:
            grouped.append(section)
            covered.update(str(item) for item in section.get("group_ids") or [])
            return

        for child in split_children:
            emit_or_split(child)

        residual_ids = _residual_group_ids(
            root_id,
            children=children,
            covered=covered,
        )
        if len(residual_ids) <= 1:
            covered.add(root_id)
            return

        residual = _emit_lineage_section(
            root=root,
            rows=rows,
            index=index,
            children=children,
            group_ids=residual_ids,
        )
        if _residual_worth_extracting(residual, index=index):
            grouped.append(residual)
            covered.update(residual_ids)
        else:
            covered.update(residual_ids)

    for row in rows:
        row_id = str(row.get("row_id") or "")
        if not row_id or row_id in covered:
            continue
        if not _is_lineage_section_root(row, index=index, children=children):
            continue
        emit_or_split(row)

    return grouped
