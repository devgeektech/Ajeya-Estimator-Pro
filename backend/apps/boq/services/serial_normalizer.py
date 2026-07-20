"""Serial-number hierarchy for BOQ rows.

Preserves workbook structure by interpreting serial markers such as ``1``,
``1.1``, ``a``, ``(a)``, and ``(1)`` as parent/child relationships.
"""
from __future__ import annotations

import re
from typing import Any

_DECIMAL_SERIAL = re.compile(r"^(\d+(?:\.\d+)*)$")
_INTEGER_SERIAL = re.compile(r"^\d+$")
_ALPHA_SERIAL = re.compile(r"^[a-zA-Z]$")
_PAREN_ALPHA = re.compile(r"^\(([a-zA-Z])\)$")
_PAREN_NUM = re.compile(r"^\((\d+)\)$")
_DESC_ALPHA = re.compile(r"^\(?([a-zA-Z])\)?[\).:\-]\s*")
# Roman-numeral continuations under lettered products (i / ii / iii / iv…).
_ROMAN_CONT = re.compile(
    r"^(?:\(\s*)?(i{1,3}|iv|vi{0,3}|ix|x|v)(?:\s*[\).:\-]|\s+)\s*",
    re.IGNORECASE,
)
_CONT_SERIAL = re.compile(r"^(\d+(?:\.\d+)*)\s*cont\.?.*$", re.IGNORECASE)
_SPEC_CONTINUATION = re.compile(
    r"operating\s*temp|temp\.?\s*:|pressure\s*:|speed\s*:|head\s*:|flow\s*:|"
    r"voltage\s*:|rpm\s*:|capacity\s*:",
    re.IGNORECASE,
)

DESCRIPTION_KEYS = ("description", "desc", "particulars", "item_description")

SERIAL_HEADER_HINTS = frozenset(
    {
        "sr",
        "sr_no",
        "s_no",
        "sl_no",
        "serial",
        "serial_no",
        "item_no",
        "sno",
        "no",
        "item",
    }
)


def normalize_serial_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].replace(".", "").isdigit():
        return text[:-2]
    return text


def _fix_float_serial_truncation(serial: str, last_serial: str) -> str:
    """Fix Excel truncating '2.10' to float 2.1 by using the previous serial context."""
    if not serial or not last_serial:
        return serial

    try:
        serial_float = float(serial)
    except ValueError:
        return serial

    match_last = re.compile(r"^(\d+)\.(\d+)$").match(last_serial)
    if not match_last:
        return serial

    prefix = match_last.group(1)
    last_num = int(match_last.group(2))

    for offset in range(1, 10):
        expected = f"{prefix}.{last_num + offset}"
        try:
            if serial_float == float(expected):
                return expected
        except ValueError:
            pass

    return serial


def _normalize_continuation_serial(serial: str) -> str:
    """Map ``1.1 Cont..`` → ``1.1`` so continuation lines share the item serial."""
    if not serial:
        return serial
    match = _CONT_SERIAL.match(serial.strip())
    if match:
        return match.group(1)
    return serial


def cell_value(row: dict, key: str) -> Any:
    """Return the UI cell value, preferring display_values over raw values."""
    display_values = row.get("display_values") or {}
    value = display_values.get(key)
    if value not in (None, ""):
        return value
    values = row.get("values") or {}
    value = values.get(key)
    if value is None:
        return ""
    return value


def structure_for_display(structure: dict) -> dict:
    """Attach ordered ``cells`` lists to rows for template rendering."""
    if not structure:
        return {}
    headers = structure.get("headers") or []
    rows = []
    for row in structure.get("rows") or []:
        rows.append(
            {
                **row,
                "cells": [cell_value(row, header["key"]) for header in headers],
            }
        )
    return {**structure, "rows": rows}


def _prefer_make_list_sheet_rows(flat_rows: list[dict]) -> list[dict]:
    """When legacy JSON mixed sheets, keep only MAKE LIST / make-named rows."""
    sheet_names = {
        str(row.get("sheet_name") or "").strip()
        for row in flat_rows
        if str(row.get("sheet_name") or "").strip()
    }
    if len(sheet_names) <= 1:
        return flat_rows

    preferred = [
        name
        for name in sheet_names
        if "make list" in name.casefold()
        or name.casefold() in {"makes", "make", "approved makes"}
    ]
    if not preferred:
        preferred = [name for name in sheet_names if "make" in name.casefold()]
    if not preferred:
        return flat_rows

    preferred_set = {name.casefold() for name in preferred}
    filtered = [
        row
        for row in flat_rows
        if str(row.get("sheet_name") or "").strip().casefold() in preferred_set
    ]
    return filtered or flat_rows


def structure_for_make_list_display(structure: dict) -> dict:
    """
    Make List tab: only S.No, Description/Material, and Approved Makes.

    Ignores leftover rate/estimate columns from older multi-sheet merges.
    """
    if not structure:
        return {}

    roles = structure.get("column_roles") or {}
    serial_key = structure.get("serial_key")
    flat_rows = _prefer_make_list_sheet_rows(list(structure.get("rows") or []))

    def _key_has_content(key: str) -> bool:
        for row in flat_rows[:40]:
            if str(cell_value(row, key) or "").strip():
                return True
        return False

    material_candidates: list[str] = []
    for key in ("description", "material", "particulars", "item_description", "desc"):
        material_candidates.append(key)
    for key in roles.get("material_keys") or []:
        if key not in material_candidates:
            material_candidates.append(str(key))

    material_key = next((key for key in material_candidates if _key_has_content(key)), None)
    if material_key is None:
        material_key = material_candidates[0] if material_candidates else "description"

    display_headers: list[dict] = []
    if serial_key:
        label = next(
            (
                str(header.get("label") or serial_key)
                for header in (structure.get("headers") or [])
                if header.get("key") == serial_key
            ),
            "S. No.",
        )
        display_headers.append({"key": serial_key, "label": label})

    material_label = next(
        (
            str(header.get("label") or material_key)
            for header in (structure.get("headers") or [])
            if header.get("key") == material_key
        ),
        "Description",
    )
    if material_key in {"description", "desc", "particulars", "item_description"}:
        material_label = "Description"
    elif "material" in str(material_key).lower():
        material_label = "Material"
    display_headers.append({"key": material_key, "label": material_label})
    display_headers.append({"key": "_mapped_category", "label": "Mapped Category"})
    display_headers.append({"key": "_approved_makes", "label": "Approved Makes"})

    rows: list[dict] = []
    header_like = {
        "s.no.",
        "s. no.",
        "s no",
        "sl.no.",
        "serial",
        "description",
        "particulars",
        "material",
        "approved makes",
        "make",
        "amount",
        "qty",
        "unit",
        "rate",
    }
    for row in flat_rows:
        makes = row.get("approved_makes_list")
        if makes is None:
            from utils.make_list_splits import collect_approved_makes

            makes = collect_approved_makes(
                row,
                make_keys=list(roles.get("make_keys") or []) or None,
            )
        makes_text = " / ".join(str(item).strip() for item in (makes or []) if str(item).strip())
        material_text = cell_value(row, material_key)
        serial_text = cell_value(row, serial_key) if serial_key else ""
        material_norm = str(material_text or "").strip().casefold()
        serial_norm = str(serial_text or "").strip().casefold()
        if material_norm in header_like or serial_norm in header_like:
            continue
        if not str(material_text or "").strip() and not makes_text:
            continue
        mapped_category = str(row.get("mapped_category") or "").strip()
        mapped_sub = str(row.get("mapped_sub_category") or "").strip()
        mapped_text = mapped_category
        if mapped_category and mapped_sub:
            mapped_text = f"{mapped_category} / {mapped_sub}"
        cells = []
        if serial_key:
            cells.append(serial_text)
        cells.append(material_text)
        cells.append(mapped_text)
        cells.append(makes_text)
        rows.append(
            {
                **row,
                "cells": cells,
                "approved_makes_list": list(makes or []),
                "mapped_category": mapped_category or None,
                "mapped_sub_category": mapped_sub or None,
            }
        )

    return {
        **structure,
        "headers": display_headers,
        "rows": rows,
        "row_count": len(rows),
    }


def analysis_fields(row: dict) -> dict[str, Any]:
    """Return clean cell values for AI / analysis (prefers ``display_values``)."""
    display_values = row.get("display_values") or {}
    if display_values:
        return dict(display_values)
    return dict(row.get("values") or {})


def _analysis_node(row: dict) -> dict[str, Any]:
    node = {
        "row_id": row.get("row_id"),
        "serial": row.get("serial", ""),
        "depth": row.get("depth", 0),
        "excel_row_number": row.get("excel_row_number"),
        "fields": analysis_fields(row),
        "children": [],
    }
    if row.get("sheet_name"):
        node["sheet_name"] = row.get("sheet_name")
    if row.get("approved_makes_list") is not None:
        node["approved_makes_list"] = row.get("approved_makes_list") or []
    return node


def nest_rows_hierarchy(flat_rows: list[dict]) -> list[dict]:
    """Build a nested tree from flat rows using ``parent_row_id`` links."""
    nodes: dict[str, dict] = {}
    roots: list[dict] = []

    for row in flat_rows:
        row_id = row.get("row_id")
        if not row_id:
            continue
        nodes[row_id] = _analysis_node(row)

    for row in flat_rows:
        row_id = row.get("row_id")
        if not row_id or row_id not in nodes:
            continue
        parent_id = row.get("parent_row_id")
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(nodes[row_id])
        else:
            roots.append(nodes[row_id])

    return roots


def structure_for_analysis(structure: dict) -> dict:
    """Return payload with nested ``rows_tree`` for AI extraction workflows."""
    if not structure:
        return {}
    flat_rows = structure.get("rows") or []
    return {
        **structure,
        "rows_tree": nest_rows_hierarchy(flat_rows),
    }


def detect_serial_key(headers: list[dict]) -> str | None:
    for header in headers:
        key = header.get("key", "")
        if key in SERIAL_HEADER_HINTS:
            return key
    for header in headers:
        key = header.get("key", "")
        if any(hint in key for hint in ("serial", "sr_", "_sr", "s_no", "sl_no")):
            return key
    if headers:
        return headers[0]["key"]
    return None


def _description_text(record: dict) -> str:
    for key in DESCRIPTION_KEYS:
        text = str(cell_value(record, key) or "").strip()
        if text:
            return text
    return ""


def _infer_serial_from_description(record: dict) -> str:
    """Infer alpha serial markers such as ``a)`` from the description column."""
    text = _description_text(record)
    if not text:
        return ""
    # Prefer roman continuations so ``i)`` / ``ii)`` are not treated as product letters.
    if _ROMAN_CONT.match(text):
        return ""
    match = _DESC_ALPHA.match(text)
    if match:
        return match.group(1).lower()
    return ""


def _leading_indent_depth(record: dict) -> int | None:
    """Estimate nesting from leading whitespace when serials are sparse."""
    for key in DESCRIPTION_KEYS:
        raw = ""
        display_values = record.get("display_values") or {}
        values = record.get("values") or {}
        if key in display_values and display_values[key] is not None:
            raw = str(display_values[key])
        elif key in values and values[key] is not None:
            raw = str(values[key])
        if not raw or not raw[0].isspace():
            continue
        leading = len(raw) - len(raw.lstrip(" \t"))
        if leading <= 0:
            continue
        # Rough: 2 spaces or 1 tab ≈ one depth level.
        tabs = raw[:leading].count("\t")
        spaces = leading - tabs
        return tabs + max(1, spaces // 2)
    return None


def _is_structural_serial(serial_key: str) -> bool:
    """Return True for top-level section serials like ``1`` or ``1.1``."""
    return bool(_INTEGER_SERIAL.match(serial_key) or _DECIMAL_SERIAL.match(serial_key))


def _is_product_alpha(serial: str) -> bool:
    alpha = serial
    paren = _PAREN_ALPHA.match(serial)
    if paren:
        alpha = paren.group(1)
    return bool(_ALPHA_SERIAL.match(alpha))


def _is_spec_continuation_row(serial: str, description: str) -> bool:
    """True for Operating Temp / roman-numeral lines that belong under a lettered product."""
    text = (description or "").strip()
    if _ROMAN_CONT.match(text):
        return True
    if serial and _ROMAN_CONT.match(f"{serial}) "):
        return True
    # Single letter ``i`` often marks roman ``i)`` under a/b products.
    if serial and serial.lower() == "i" and _SPEC_CONTINUATION.search(text):
        return True
    if not serial and _SPEC_CONTINUATION.search(text):
        return True
    return False


def _structural_parent(stack: list[dict]) -> dict | None:
    """Return the nearest integer/decimal parent for continuation or alpha rows."""
    for item in reversed(stack):
        if item.get("kind") == "structural" or _is_structural_serial(item["serial_key"]):
            return item
    return None


def _last_product_alpha(stack: list[dict]) -> dict | None:
    for item in reversed(stack):
        if item.get("kind") == "alpha":
            return item
    return None


def _child_of_structural_parent(stack: list[dict]) -> tuple[int, str | None]:
    parent = _structural_parent(stack)
    if not parent:
        return 0, None
    return parent["depth"] + 1, parent["serial_key"]


def _resolve_parent_row_id(
    parent_serial_key: str | None,
    *,
    parent_row_id_direct: str | None,
    serial_lookup: dict[str, list[str]],
) -> str | None:
    if parent_row_id_direct:
        return parent_row_id_direct
    if not parent_serial_key:
        return None
    prior = serial_lookup.get(parent_serial_key) or []
    return prior[-1] if prior else None


def _serial_depth_and_parent(
    serial: str,
    stack: list[dict],
    *,
    description: str,
    indent_depth: int | None,
) -> tuple[int, str | None, str | None, str]:
    """
    Return ``(depth, parent_serial_key, parent_row_id_direct, kind)``.

    ``kind`` is ``structural`` | ``alpha`` | ``continuation``.
    ``parent_row_id_direct`` bypasses serial lookup when parenting under a lettered product.
    """
    # Spec / roman lines → nest under last lettered product.
    if serial and _is_spec_continuation_row(serial, description):
        alpha_parent = _last_product_alpha(stack)
        if alpha_parent:
            return (
                alpha_parent["depth"] + 1,
                alpha_parent["serial_key"],
                alpha_parent["row_id"],
                "continuation",
            )

    if not serial:
        # Blank under an open lettered product (or its continuations) stays there.
        # Blank after a structural row stays under the structural parent.
        if stack and stack[-1].get("kind") in {"alpha", "continuation"}:
            alpha_parent = _last_product_alpha(stack)
            if alpha_parent:
                return (
                    alpha_parent["depth"] + 1,
                    alpha_parent["serial_key"],
                    alpha_parent["row_id"],
                    "continuation",
                )
        if indent_depth is not None and stack:
            parent = None
            for item in reversed(stack):
                if item["depth"] < indent_depth:
                    parent = item
                    break
            if parent:
                return indent_depth, parent["serial_key"], parent["row_id"], "continuation"
        if not stack:
            return 0, None, None, "continuation"
        depth, parent_key = _child_of_structural_parent(stack)
        return depth, parent_key, None, "continuation"

    decimal_match = _DECIMAL_SERIAL.match(serial)
    if decimal_match:
        parts = serial.split(".")
        depth = len(parts) - 1
        parent_key = ".".join(parts[:-1]) if depth else None
        return depth, parent_key, None, "structural"

    if _INTEGER_SERIAL.match(serial):
        return 0, None, None, "structural"

    paren_num = _PAREN_NUM.match(serial)
    if paren_num:
        return 1, paren_num.group(1), None, "alpha"

    alpha = serial
    paren_alpha = _PAREN_ALPHA.match(serial)
    if paren_alpha:
        alpha = paren_alpha.group(1)

    if _ALPHA_SERIAL.match(alpha):
        # Spec-like lettered ``i)`` under a/b product.
        if _is_spec_continuation_row(serial, description):
            alpha_parent = _last_product_alpha(stack)
            if alpha_parent:
                return (
                    alpha_parent["depth"] + 1,
                    alpha_parent["serial_key"],
                    alpha_parent["row_id"],
                    "continuation",
                )
        if not stack:
            return 0, None, None, "alpha"
        depth, parent_key = _child_of_structural_parent(stack)
        return depth, parent_key, None, "alpha"

    if stack:
        depth, parent_key = _child_of_structural_parent(stack)
        return depth, parent_key, None, "continuation"
    return 0, None, None, "continuation"


def attach_row_hierarchy(
    records: list[dict],
    *,
    serial_key: str | None,
) -> list[dict]:
    """Attach ``row_id``, ``serial``, ``depth``, and ``parent_row_id`` to records."""
    # Map serial → ordered row_ids (nearest prior parent = last entry).
    serial_lookup: dict[str, list[str]] = {}
    stack: list[dict] = []
    normalized_rows: list[dict] = []

    last_structural_serial = ""
    sheet_names = {
        str(record.get("sheet_name") or "")
        for record in records
        if record.get("sheet_name")
    }
    multi_sheet = len(sheet_names) > 1

    for index, record in enumerate(records, start=1):
        serial = ""
        if serial_key:
            serial = normalize_serial_text(cell_value(record, serial_key))
            fixed_serial = _fix_float_serial_truncation(serial, last_structural_serial)
            if fixed_serial != serial:
                serial = fixed_serial
                if "display_values" in record and serial_key in record["display_values"]:
                    record["display_values"][serial_key] = serial
                if "values" in record and serial_key in record["values"]:
                    record["values"][serial_key] = serial

        serial = _normalize_continuation_serial(serial)

        if not serial:
            serial = _infer_serial_from_description(record)

        description = _description_text(record)
        indent_depth = _leading_indent_depth(record)
        depth, parent_serial_key, parent_row_direct, kind = _serial_depth_and_parent(
            serial,
            stack,
            description=description,
            indent_depth=indent_depth,
        )

        sheet_name = str(record.get("sheet_name") or "")
        excel_row = record.get("excel_row_number", index)
        if multi_sheet and sheet_name:
            safe_sheet = re.sub(r"[^0-9a-zA-Z]+", "_", sheet_name).strip("_") or "sheet"
            row_id = f"r{safe_sheet}_{excel_row}"
        else:
            row_id = f"r{excel_row}"

        parent_row_id = _resolve_parent_row_id(
            parent_serial_key,
            parent_row_id_direct=parent_row_direct,
            serial_lookup=serial_lookup,
        )

        while stack and stack[-1]["depth"] >= depth:
            stack.pop()

        row = {
            **record,
            "row_id": row_id,
            "serial": serial,
            "depth": depth,
            "parent_row_id": parent_row_id,
            "row_index": index,
        }
        normalized_rows.append(row)

        if serial:
            serial_lookup.setdefault(serial, []).append(row_id)
            stack.append(
                {
                    "depth": depth,
                    "serial_key": serial,
                    "row_id": row_id,
                    "kind": kind,
                }
            )
        elif kind == "continuation":
            # Keep blank/spec rows on the stack so following blanks stay nested
            # under the open lettered product.
            stack.append(
                {
                    "depth": depth,
                    "serial_key": parent_serial_key or f"__cont_{row_id}",
                    "row_id": parent_row_id or row_id,
                    "kind": "continuation",
                    "owner_row_id": parent_row_id,
                }
            )
        elif kind == "alpha":
            stack.append(
                {
                    "depth": depth,
                    "serial_key": f"__alpha_{row_id}",
                    "row_id": row_id,
                    "kind": "alpha",
                }
            )

        if kind == "structural" and serial and _is_structural_serial(serial):
            last_structural_serial = serial

    return normalized_rows
