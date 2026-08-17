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
# Common BOQ forms: a)  b)  A)
_SUFFIX_ALPHA = re.compile(r"^([a-zA-Z])\)$")
_PAREN_NUM = re.compile(r"^\((\d+)\)$")
# Letter markers in description: (a) / a) / a: / a- / a.<space>
# Do NOT treat ``M.S.`` / ``C.I.`` / ``D.I.`` as serial ``m)`` / ``c)`` / ``d)``.
_DESC_ALPHA = re.compile(
    r"^(?:"
    r"\(([a-zA-Z])\)\s*"  # (a)
    r"|([a-zA-Z])\)\s*"  # a)
    r"|([a-zA-Z])[:\-]\s+"  # a: or a-
    r"|([a-zA-Z])\.\s+"  # a. with required space (not M.S.)
    r")"
)
# Material abbreviations that look like letter serials if ``.`` is allowed bare.
_MATERIAL_DESC_PREFIX = re.compile(
    r"^(?:m\.?\s*s\.?|c\.?\s*i\.?|d\.?\s*i\.?|g\.?\s*i\.?|s\.?\s*s\.?)\b",
    re.IGNORECASE,
)
# Standalone section romans (I, II, III…) — not product-line continuations.
_SECTION_ROMAN = re.compile(r"^(?:i{1,3}|iv|vi{0,3}|ix|x|v)$", re.IGNORECASE)
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


def workbook_serial(row: dict[str, Any], *, serial_key: str | None = None) -> str:
    """Original BOQ serial text for Review/export (preserve client numbering)."""
    if serial_key:
        text = normalize_serial_text(cell_value(row, serial_key))
        if text:
            return text
    attached = normalize_serial_text(row.get("serial"))
    if attached:
        return attached
    return str(row.get("serial") or "").strip()


def nearest_structural_serial(
    row_id: str,
    rows_by_id: dict[str, dict[str, Any]],
    *,
    serial_key: str | None = None,
    start_at_parent: bool = True,
) -> str:
    """
    Walk ``parent_row_id`` to the nearest structural serial (``1``, ``1.1``, ``5.2``).

    When ``start_at_parent`` is True (default), skip the starting row itself so a
    lettered qty row like ``a)`` resolves to its section parent (``5.1``), not ``a)``.
    """
    current_id = str(row_id or "").strip()
    if not current_id:
        return ""
    start = rows_by_id.get(current_id)
    if start_at_parent and start is not None:
        current_id = str(start.get("parent_row_id") or "").strip()
    seen: set[str] = set()
    while current_id and current_id not in seen:
        seen.add(current_id)
        row = rows_by_id.get(current_id)
        if row is None:
            break
        serial = workbook_serial(row, serial_key=serial_key)
        if serial and _is_structural_serial(serial):
            return serial
        current_id = str(row.get("parent_row_id") or "").strip()
    return ""


def export_serial_with_suffix(base_serial: str, occurrence_index: int, total_for_base: int) -> str:
    """Keep original serial; suffix (A)/(B)/(C) only when multiple products share it."""
    base = str(base_serial or "").strip() or "—"
    if total_for_base <= 1:
        return base
    letter = chr(ord("A") + max(0, int(occurrence_index)))
    return f"{base}({letter})"


def _clean_header_label(label: Any) -> str:
    """Collapse Excel multiline header cells to one line — keep workbook wording."""
    text = str(label or "").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _format_display_serial(serial: Any) -> str:
    """Present inferred letter serials as ``a)`` for the BOQ sheet S.No column."""
    text = str(serial or "").strip()
    if not text:
        return ""
    if _ALPHA_SERIAL.match(text):
        return f"{text.lower()})"
    return text


def _sheet_col_class(header: dict) -> str:
    """CSS column class for a BOQ sheet header (drives column width)."""
    blob = re.sub(
        r"[^a-z0-9]+",
        " ",
        f"{header.get('key') or ''} {header.get('label') or ''}".casefold(),
    ).strip()
    if any(hint in blob for hint in ("s no", "sno", "sl no", "sr no", "serial")):
        return "boq-sheet__col-sno"
    if any(hint in blob for hint in ("description", "particular", "material", "item desc")):
        return "boq-sheet__col-desc"
    if "unit" in blob and "quantity" not in blob:
        return "boq-sheet__col-unit"
    if "qty" in blob or "quantity" in blob:
        return "boq-sheet__col-qty"
    if "rate" in blob:
        return "boq-sheet__col-rate"
    if "amount" in blob or ("total" in blob and "qty" not in blob):
        return "boq-sheet__col-amount"
    # Floor / location breakdown qty columns (GF, 1st, External+Terrace…).
    if any(
        hint in blob
        for hint in (
            "external",
            "terrace",
            "pump room",
            "basement",
            "ground",
            " gf",
            "gf ",
            "1st",
            "2nd",
            "3rd",
            "floor",
        )
    ) or blob in {"gf", "1st", "2nd", "3rd"}:
        return "boq-sheet__col-floor"
    return "boq-sheet__col-other"


def _display_cell_text(value: Any) -> Any:
    """Normalize cell text for UI (drop leading/trailing Excel whitespace)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    return value


def _with_display_cells(headers: list[dict], cells: list) -> list[dict]:
    """Pair each cell with its header column class for template rendering."""
    return [
        {"text": _display_cell_text(value), "col_class": header.get("col_class") or ""}
        for header, value in zip(headers, cells)
    ]


def structure_for_display(structure: dict) -> dict:
    """Attach ordered ``cells`` lists to rows for template rendering.

    Columns marked ``hidden`` (Excel-hidden in the uploaded workbook) are
    omitted from the BOQ tab so the UI matches what the user sees in Excel.
    Stored ``boq_data`` still keeps those columns for analysis / export.
    """
    if not structure:
        return {}
    serial_key = structure.get("serial_key") or detect_serial_key(
        list(structure.get("headers") or [])
    )
    headers = []
    for header in structure.get("headers") or []:
        if header.get("hidden"):
            continue
        cleaned_label = _clean_header_label(header.get("label") or header.get("key") or "")
        labeled = {**header, "label": cleaned_label}
        headers.append(
            {
                **labeled,
                "col_class": _sheet_col_class(labeled),
            }
        )

    rows = []
    for row in structure.get("rows") or []:
        cells = [cell_value(row, header["key"]) for header in headers]
        # When Excel leaves S.No blank but we inferred ``a)`` / ``b)`` from the
        # description, surface that serial in the S.No column for the BOQ tab.
        if serial_key:
            for index, header in enumerate(headers):
                if header.get("key") != serial_key:
                    continue
                if cells[index] in (None, ""):
                    inferred = _format_display_serial(row.get("serial"))
                    desc = _description_text(row)
                    if inferred and not _is_bogus_material_serial(inferred, desc):
                        cells[index] = inferred
                break
        rows.append(
            {
                **row,
                "cells": cells,
                "display_cells": _with_display_cells(headers, cells),
            }
        )
    return {**structure, "headers": headers, "rows": rows}


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


def _make_list_sheet_col_class(header: dict, serial_key: str | None) -> str:
    """CSS column class for Make List display headers."""
    key = str(header.get("key") or "")
    if key == "_approved_makes":
        return "boq-sheet__col-makes"
    if key == "_mapped_category":
        return "boq-sheet__col-mapped-cat"
    if key == "_mapped_sub_category":
        return "boq-sheet__col-mapped-sub"
    if serial_key and key == serial_key:
        return "boq-sheet__col-sno"
    return "boq-sheet__col-desc"


def structure_for_make_list_display(structure: dict) -> dict:
    """
    Make List tab: S.No, Description/Material, Category,
    Subcategory, and Approved Makes.

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
    display_headers.append({"key": "_mapped_category", "label": "Category"})
    display_headers.append({"key": "_mapped_sub_category", "label": "Subcategory"})
    display_headers.append({"key": "_approved_makes", "label": "Approved Makes"})
    display_headers = [
        {**header, "col_class": _make_list_sheet_col_class(header, serial_key)}
        for header in display_headers
    ]

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
        is_section = bool(row.get("is_section_heading"))
        makes = row.get("approved_makes_list")
        if makes is None and not is_section:
            from utils.make_list_splits import collect_approved_makes

            makes = collect_approved_makes(
                row,
                make_keys=list(roles.get("make_keys") or []) or None,
            )
        if is_section:
            makes = []
        makes_text = " / ".join(str(item).strip() for item in (makes or []) if str(item).strip())
        material_text = cell_value(row, material_key)
        serial_text = cell_value(row, serial_key) if serial_key else ""
        material_norm = str(material_text or "").strip().casefold()
        serial_norm = str(serial_text or "").strip().casefold()
        if material_norm in header_like or serial_norm in header_like:
            continue
        # Keep description-only rows (empty Approved Makes) and section banners.
        if not str(material_text or "").strip() and not makes_text and not is_section:
            continue
        mapped_category = "" if is_section else str(
            row.get("mapped_category_display") or row.get("mapped_category") or ""
        ).strip()
        mapped_sub = "" if is_section else str(
            row.get("mapped_sub_category_display") or row.get("mapped_sub_category") or ""
        ).strip()
        if not is_section and not mapped_category and row.get("mapped_targets"):
            from apps.boq.services.make_list_category_mapping_service import (
                format_mapped_targets_display,
            )

            mapped_category, mapped_sub = format_mapped_targets_display(
                row.get("mapped_targets"),
                category=row.get("mapped_category"),
                sub_category=row.get("mapped_sub_category"),
            )
        cells = []
        if serial_key:
            cells.append("" if is_section else serial_text)
        cells.append(material_text)
        cells.append(mapped_category)
        cells.append(mapped_sub)
        cells.append("" if is_section else makes_text)
        rows.append(
            {
                **row,
                # Make List is a flat sheet — never inherit BOQ hierarchy indent.
                "depth": 0,
                "cells": cells,
                "display_cells": _with_display_cells(display_headers, cells),
                "approved_makes_list": [] if is_section else list(makes or []),
                "mapped_category": None if is_section else (row.get("mapped_category") or None),
                "mapped_sub_category": None
                if is_section
                else (row.get("mapped_sub_category") or None),
                "mapped_targets": [] if is_section else list(row.get("mapped_targets") or []),
                "mapped_category_display": None if is_section else (mapped_category or None),
                "mapped_sub_category_display": None if is_section else (mapped_sub or None),
                "is_section_heading": is_section,
                "row_class": "make-list-sheet__row--section" if is_section else "",
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
    if row.get("is_section_heading"):
        node["is_section_heading"] = True
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
    # M.S. / C.I. / D.I. / G.I. / S.S. are materials, not letter serials.
    if _MATERIAL_DESC_PREFIX.match(text):
        return ""
    # Prefer roman continuations so ``i)`` / ``ii)`` are not treated as product letters.
    if _ROMAN_CONT.match(text):
        return ""
    match = _DESC_ALPHA.match(text)
    if match:
        letter = next((group for group in match.groups() if group), "")
        if not letter:
            return ""
        # Keep the common BOQ form ``a)`` so S.No / hierarchy match the sheet.
        return f"{letter.lower()})"
    return ""


def _is_bogus_material_serial(serial: str, description: str) -> bool:
    """True when stored ``m)`` / ``c)`` came from ``M.S.`` / ``C.I.`` description lead."""
    letter = letter_from_serial(serial)
    if not letter:
        return False
    if not _MATERIAL_DESC_PREFIX.match(description or ""):
        return False
    # Only clear when the letter matches the material lead (m←MS, c←CI, …).
    material = _MATERIAL_DESC_PREFIX.match(description or "")
    if not material:
        return False
    lead = re.sub(r"[^a-z]", "", material.group(0).lower())
    return lead[:1] == letter.lower()


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


def letter_from_serial(serial: str) -> str | None:
    """Return the single letter for ``a``, ``(A)``, ``a)`` forms; else None."""
    text = str(serial or "").strip()
    if not text:
        return None
    if _ALPHA_SERIAL.match(text):
        return text
    paren = _PAREN_ALPHA.match(text)
    if paren:
        return paren.group(1)
    suffix = _SUFFIX_ALPHA.match(text)
    if suffix:
        return suffix.group(1)
    return None


def _is_product_alpha(serial: str) -> bool:
    return letter_from_serial(serial) is not None


def _is_section_roman(serial: str) -> bool:
    """True for standalone section markers ``I`` / ``II`` / ``III`` / ``IV``…"""
    return bool(_SECTION_ROMAN.match(str(serial or "").strip()))


is_section_roman = _is_section_roman


def _is_spec_continuation_row(serial: str, description: str) -> bool:
    """True for Operating Temp / roman-numeral lines that belong under a lettered product."""
    text = (description or "").strip()
    serial_text = str(serial or "").strip()
    # Section headers like ``III SPRINKLER SYSTEM`` are top-level, not continuations.
    if serial_text and _is_section_roman(serial_text) and not _SPEC_CONTINUATION.search(text):
        return False
    if _ROMAN_CONT.match(text):
        return True
    if serial_text and _ROMAN_CONT.match(f"{serial_text}) "):
        # Bare section roman without trailing punctuation is not a continuation.
        if _is_section_roman(serial_text) and not re.search(r"[).:\-]", serial_text):
            return False
        return True
    # Single letter ``i`` often marks roman ``i)`` under a/b products.
    if serial_text and serial_text.lower() == "i" and _SPEC_CONTINUATION.search(text):
        return True
    if not serial_text and _SPEC_CONTINUATION.search(text):
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

    # Section romans (I, II, III…) are top-level chapter markers.
    if serial and _is_section_roman(serial) and not _is_product_alpha(serial):
        return 0, None, None, "structural"
    # Single-letter ``I`` / ``V`` used as section titles (not product a/b/c).
    if serial and _is_section_roman(serial) and _is_product_alpha(serial):
        # Prefer section when description looks like a chapter title (short, no specs).
        text = (description or "").strip()
        if text and not _SPEC_CONTINUATION.search(text) and len(text) < 80:
            return 0, None, None, "structural"

    if not serial:
        # Blank spec lines (Speed / Head / Capacity) stay under the open product
        # or the nearest structural item — never float up to a distant section.
        if _is_spec_continuation_row(serial, description):
            alpha_parent = _last_product_alpha(stack)
            if alpha_parent:
                return (
                    alpha_parent["depth"] + 1,
                    alpha_parent["serial_key"],
                    alpha_parent["row_id"],
                    "continuation",
                )
            structural = _structural_parent(stack)
            if structural:
                return (
                    structural["depth"] + 1,
                    structural["serial_key"],
                    structural["row_id"],
                    "continuation",
                )
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
        structural = _structural_parent(stack)
        parent_row = structural["row_id"] if structural else None
        return depth, parent_key, parent_row, "continuation"

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

    letter = letter_from_serial(serial)
    if letter:
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
