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


def _infer_serial_from_description(record: dict) -> str:
    """Infer alpha serial markers such as ``a)`` from the description column."""
    for key in DESCRIPTION_KEYS:
        text = str(cell_value(record, key) or "").strip()
        if not text:
            continue
        match = _DESC_ALPHA.match(text)
        if match:
            return match.group(1).lower()
    return ""


def _is_structural_serial(serial_key: str) -> bool:
    """Return True for top-level section serials like ``1`` or ``1.1``."""
    return bool(_INTEGER_SERIAL.match(serial_key) or _DECIMAL_SERIAL.match(serial_key))


def _structural_parent(stack: list[dict]) -> dict | None:
    """Return the nearest integer/decimal parent for continuation or alpha rows."""
    for item in reversed(stack):
        if _is_structural_serial(item["serial_key"]):
            return item
    return None


def _child_of_structural_parent(stack: list[dict]) -> tuple[int, str | None]:
    parent = _structural_parent(stack)
    if not parent:
        return 0, None
    return parent["depth"] + 1, parent["serial_key"]


def _serial_depth_and_parent_key(serial: str, stack: list[dict]) -> tuple[int, str | None]:
    """Return hierarchy depth and parent serial key for one row."""
    if not serial:
        if not stack:
            return 0, None
        return _child_of_structural_parent(stack)

    decimal_match = _DECIMAL_SERIAL.match(serial)
    if decimal_match:
        parts = serial.split(".")
        depth = len(parts) - 1
        parent_key = ".".join(parts[:-1]) if depth else None
        return depth, parent_key

    if _INTEGER_SERIAL.match(serial):
        return 0, None

    paren_num = _PAREN_NUM.match(serial)
    if paren_num:
        return 1, paren_num.group(1)

    alpha = serial
    paren_alpha = _PAREN_ALPHA.match(serial)
    if paren_alpha:
        alpha = paren_alpha.group(1)

    if _ALPHA_SERIAL.match(alpha):
        if not stack:
            return 0, None
        return _child_of_structural_parent(stack)

    if stack:
        return _child_of_structural_parent(stack)
    return 0, None


def attach_row_hierarchy(
    records: list[dict],
    *,
    serial_key: str | None,
) -> list[dict]:
    """Attach ``row_id``, ``serial``, ``depth``, and ``parent_row_id`` to records."""
    serial_lookup: dict[str, str] = {}
    stack: list[dict] = []
    normalized_rows: list[dict] = []

    for index, record in enumerate(records, start=1):
        serial = ""
        if serial_key:
            serial = normalize_serial_text(cell_value(record, serial_key))
        if not serial:
            serial = _infer_serial_from_description(record)

        depth, parent_serial_key = _serial_depth_and_parent_key(serial, stack)
        row_id = f"r{record.get('excel_row_number', index)}"
        parent_row_id = serial_lookup.get(parent_serial_key) if parent_serial_key else None

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
            serial_lookup[serial] = row_id
            stack.append({"depth": depth, "serial_key": serial, "row_id": row_id})

    return normalized_rows
