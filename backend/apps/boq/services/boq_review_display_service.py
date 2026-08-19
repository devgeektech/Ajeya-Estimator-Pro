"""Shape Make & Vendor + Labour product lines for Review and export."""
from __future__ import annotations

from collections import Counter
from typing import Any

from apps.boq.models import BOQ
from apps.boq.services.boq_extraction_service import (
    quantity_display_fields,
    rehydrate_products_quantity_from_group,
)
from apps.boq.services.boq_row_fields import (
    DESCRIPTION_KEYS as _DESCRIPTION_KEYS,
    QTY_KEYS as _QTY_KEYS,
    UNIT_KEYS as _UNIT_KEYS,
    field_from_map as _field_from_map,
    ordered_boq_rows as _ordered_boq_rows,
)
from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows
from apps.boq.services.serial_normalizer import (
    analysis_fields,
    detect_serial_key,
    display_serial_for_row,
    export_serial_with_suffix,
    format_boq_serial_text,
    workbook_serial,
)


def _qty_slot_row_ids(group_by_row: dict[str, dict[str, Any]]) -> set[str]:
    """Row ids that are Unit/Qty slots already represented as Review products."""
    ids: set[str] = set()
    for group in group_by_row.values():
        for slot in group.get("slots") or group.get("qty_rows") or []:
            slot_id = str(slot.get("qty_row_id") or slot.get("row_id") or "").strip()
            if slot_id:
                ids.add(slot_id)
        group_qty_id = str(group.get("qty_row_id") or "").strip()
        if group_qty_id:
            ids.add(group_qty_id)
    return ids

# Client Output format.xlsx columns for Review/breakdown export.
# Red headers use the exact red text from the template; instructional black
# headers are shortened to the field name only (text before the parenthetical).
# Tuple: (export header label, is_red_in_Output_format.xlsx).
REVIEW_OUTPUT_HEADER_SPECS: list[tuple[str, bool]] = [
    ("Ser no of BOQ", True),
    ("BOQ Description", True),
    ("AI based Interpretation of BOQ Item", True),
    ("Matching Rate_ID", False),
    ("Make", False),
    ("Vendor", False),
    ("Base_Purchase_Rate", False),
    ("Discount", False),
    ("Net_Material_Rate", False),
    ("Procurement_Value", False),
    ("Commercial_Material_Base", False),
    ("Accessories_Value", False),
    ("Handling_Value", False),
    ("Wastage_Value", False),
    ("Sub_Total", False),
    ("Profit_Value", False),
    ("Final_Material_Amount", False),
    # Red in template; keep the short label (instructional suffix dropped).
    ("Labour", True),
    ("Final Rate", False),
    ("Qty", False),
    ("TOTAL MATERIAL", True),
    ("TOTAL LABOUR", True),
    ("Amount", False),
]
REVIEW_OUTPUT_HEADERS = [label for label, _is_red in REVIEW_OUTPUT_HEADER_SPECS]

# Shorter labels for on-screen Review cards (subset of export columns).
REVIEW_UI_HEADERS = [
    "S. No.",
    "BOQ Description",
    "AI Interpretation",
    "Make",
    "Vendor",
    "Material amount",
    "Labour",
    "Qty",
    "TOTAL MATERIAL",
    "TOTAL LABOUR",
    "Total Amount",
]


def _product_base_serial(
    product: dict[str, Any],
    *,
    parent_serial: str,
    rows_by_id: dict[str, dict[str, Any]],
    serial_key: str | None,
) -> str:
    """
    Ser no for Review/export — mirror the uploaded BOQ Unit/Qty row S.No.

    Letter slots stay ``a)`` / ``b)``; structural item rows keep ``1.7``, ``2.10``, etc.
    """
    fallback_parent = str(parent_serial or "").strip()
    qty_row_id = ""
    for key in ("qty_row_id", "source_row_id"):
        candidate = str(product.get(key) or "").strip()
        if candidate:
            qty_row_id = candidate
            break

    source_row = rows_by_id.get(qty_row_id) if qty_row_id else None
    if source_row is not None:
        serial = display_serial_for_row(source_row, serial_key=serial_key)
        if serial:
            return serial

    child = str(product.get("boq_serial") or "").strip()
    if child:
        return format_boq_serial_text(child) or child

    return fallback_parent


def _assign_export_serials(products: list[dict[str, Any]]) -> None:
    """Preserve original serials; add (A)/(B)/(C) only when several products share one."""
    bases = [str(item.get("serial") or "").strip() or "—" for item in products]
    totals = Counter(bases)
    seen: dict[str, int] = {}
    for product, base in zip(products, bases):
        index = seen.get(base, 0)
        seen[base] = index + 1
        export_serial = export_serial_with_suffix(base, index, totals[base])
        product["serial"] = export_serial
        review_output = product.get("review_output")
        if isinstance(review_output, dict):
            review_output["serial"] = export_serial


def _product_summary(product: dict[str, Any]) -> str:
    parts = [
        str(product.get("category") or "").strip(),
        str(product.get("sub_category") or "").strip(),
        str(product.get("class") or "").strip(),
    ]
    text = " / ".join(part for part in parts if part)
    return text or str(product.get("description_hint") or "").strip() or "Product"


def _ai_interpretation(product: dict[str, Any]) -> str:
    """Human-readable AI extraction summary for the Review Output format column."""
    parts: list[str] = []
    hint = str(product.get("description_hint") or "").strip()
    if hint:
        parts.append(hint)
    for key in ("category", "sub_category", "class", "size", "capacity", "unit"):
        value = product.get(key)
        if value not in (None, ""):
            parts.append(str(value).strip())
    return " / ".join(parts) if parts else _product_summary(product)


def _qty_row_description(
    group: dict[str, Any] | None,
    product: dict[str, Any],
    *,
    product_index: int,
    fallback: str = "",
) -> str:
    """
    Description from the Unit/Qty BOQ row (a/b/c…) — not the parent header.

    Qty and unit stay in their own Review fields; do not append them here.
    """
    if not group:
        return fallback
    slots = list(group.get("slots") or group.get("qty_rows") or [])
    if not slots:
        return fallback

    by_id = {
        str(slot.get("qty_row_id") or slot.get("row_id") or ""): slot
        for slot in slots
        if slot.get("qty_row_id") or slot.get("row_id")
    }
    source_id = str(
        product.get("qty_row_id") or product.get("source_row_id") or ""
    ).strip()
    slot = by_id.get(source_id) if source_id else None
    if slot is None and 0 <= product_index < len(slots):
        slot = slots[product_index]
    if slot is None:
        slot = slots[0]

    serial = str(slot.get("serial") or "").strip()
    text = str(slot.get("description") or "").strip()
    if serial and text:
        # Avoid "a) a) 150mm dia" when description already starts with the letter.
        serial_core = serial.rstrip(").").strip().casefold()
        if text.casefold().startswith(serial_core):
            label = text
        else:
            label = f"{serial} {text}".strip()
    else:
        label = text or serial

    return label or fallback


def build_review_output_row(
    *,
    serial: Any,
    description: Any,
    product: dict[str, Any],
    selected: dict[str, Any],
    rate_detail: dict[str, Any] | None,
    line_output: dict[str, Any],
    qty: Any,
) -> dict[str, Any]:
    """One product row shaped to the client Output format.xlsx columns."""
    rd = rate_detail if isinstance(rate_detail, dict) else {}
    material_unit = (
        rd.get("final_material_amount")
        or line_output.get("material_rate")
        or rd.get("selection_amount")
    )
    labour_unit = line_output.get("labour_rate")
    return {
        "serial": serial,
        "boq_description": description,
        "ai_interpretation": _ai_interpretation(product),
        "rate_id": selected.get("rate_id") or rd.get("rate_id"),
        "make": selected.get("make") or rd.get("make") or "",
        "vendor": selected.get("vendor") or rd.get("vendor") or "",
        "base_purchase_rate": rd.get("base_purchase_rate"),
        "discount": rd.get("discount"),
        "net_material_rate": rd.get("net_material_rate"),
        "procurement_value": rd.get("procurement_value"),
        "commercial_material_base": rd.get("commercial_material_base"),
        "accessories_value": rd.get("accessories_value"),
        "handling_value": rd.get("handling_value"),
        "wastage_value": rd.get("wastage_value"),
        "sub_total": rd.get("sub_total"),
        "profit_value": rd.get("profit_value"),
        "final_material_amount": material_unit,
        "labour": labour_unit,
        # Final Rate is calculated in Excel (not here) to keep rollups as formulas.
        "final_rate": None,
        "qty": qty if qty not in (None, "") else line_output.get("quantity"),
        "total_material": line_output.get("material_amount"),
        "total_labour": line_output.get("labour_amount"),
        "amount": line_output.get("total_amount"),
    }


def review_output_values(row: dict[str, Any]) -> list[Any]:
    """Ordered cell values matching REVIEW_OUTPUT_HEADERS."""
    return [
        row.get("serial"),
        row.get("boq_description"),
        row.get("ai_interpretation"),
        row.get("rate_id"),
        row.get("make"),
        row.get("vendor"),
        row.get("base_purchase_rate"),
        row.get("discount"),
        row.get("net_material_rate"),
        row.get("procurement_value"),
        row.get("commercial_material_base"),
        row.get("accessories_value"),
        row.get("handling_value"),
        row.get("wastage_value"),
        row.get("sub_total"),
        row.get("profit_value"),
        row.get("final_material_amount"),
        row.get("labour"),
        row.get("final_rate"),
        row.get("qty"),
        row.get("total_material"),
        row.get("total_labour"),
        row.get("amount"),
    ]


class BOQReviewDisplayService:
    """Review / export display from vendor_selection (not fuzzy product_matches)."""

    def __init__(self, boq: BOQ, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq = boq
        # Confirmations unused in the new pipeline; kept for call-site compatibility.
        self.confirmations = confirmations or {}

    def build(self) -> dict[str, Any]:
        analysis = self.boq.analysis_data or {}
        boq_data = self.boq.boq_data or {}
        analysis_by_row = {
            str(row.get("row_id")): row
            for row in analysis.get("rows") or []
            if row.get("row_id")
        }
        ordered_rows = _ordered_boq_rows(boq_data)
        rows_by_id = {
            str(row.get("row_id")): row
            for row in ordered_rows
            if row.get("row_id")
        }
        serial_key = detect_serial_key(list(boq_data.get("headers") or []))
        group_by_row = {
            str(group.get("row_id") or ""): group
            for group in grouped_anchor_rows(boq_data)
            if group.get("row_id")
        }
        qty_slot_ids = _qty_slot_row_ids(group_by_row)

        lines: list[dict[str, Any]] = []
        matched_count = 0
        pending_count = 0
        product_total = 0

        for boq_row in ordered_rows:
            row_id = str(boq_row.get("row_id") or "")
            if not row_id:
                continue

            analysis_row = analysis_by_row.get(row_id, {})
            # Qty letter slots (a)/b)) are shown as products under the parent —
            # skip duplicates. Other lineage notes (Material, Fittings, Painting…)
            # stay in Review/export so the sheet mirrors the BOQ section text.
            if analysis_row.get("skip_reason") == "lineage_child_row":
                if row_id in qty_slot_ids:
                    continue
                # Treat as a structural BOQ row (no products).
                analysis_row = {
                    **analysis_row,
                    "skip_matching": True,
                    "products": [],
                }

            fields = analysis_fields(boq_row)
            serial = display_serial_for_row(boq_row, serial_key=serial_key)
            depth = boq_row.get("depth", 0)
            description = _field_from_map(fields, _DESCRIPTION_KEYS) or ""
            qty = _field_from_map(fields, _QTY_KEYS)
            unit = _field_from_map(fields, _UNIT_KEYS)
            group = group_by_row.get(row_id, {})
            # Only copy group qty onto the actual Unit/Qty slot — never the
            # section header (that put the first child's qty on row 1 of each section).
            if qty in (None, "") and group:
                slot_ids = {
                    str(slot.get("qty_row_id") or slot.get("row_id") or "").strip()
                    for slot in (group.get("slots") or group.get("qty_rows") or [])
                }
                group_qty_id = str(group.get("qty_row_id") or "").strip()
                if row_id in slot_ids or (group_qty_id and row_id == group_qty_id):
                    qty = group.get("qty")
                    unit = unit or group.get("unit")

            line_description = group.get("description") or description
            full_description = group.get("full_description") or description
            lineage_parts = list(group.get("lineage_parts") or [])
            lineage_count = int(group.get("lineage_count") or 1)

            if analysis_row.get("skip_matching"):
                lines.append(
                    {
                        "row_id": row_id,
                        "serial": serial,
                        "depth": depth,
                        "description": line_description,
                        "full_description": full_description,
                        "lineage_parts": lineage_parts,
                        "lineage_count": lineage_count,
                        "qty": qty,
                        "unit": unit,
                        "status": "skipped",
                        "products": [],
                        "product_count": 0,
                        "show_qty_unit": qty not in (None, "") or bool(unit),
                    }
                )
                continue

            raw_products = rehydrate_products_quantity_from_group(
                list(analysis_row.get("products") or []),
                group,
            )
            products: list[dict[str, Any]] = []
            for index, item in enumerate(raw_products):
                product_total += 1
                product_qty = (
                    item.get("quantity")
                    if item.get("quantity") not in (None, "")
                    else qty
                )
                product_unit = (
                    item.get("quantity_unit")
                    if item.get("quantity_unit") not in (None, "")
                    else unit
                )
                qty_fields = quantity_display_fields(
                    {
                        **item,
                        "quantity": product_qty,
                        "quantity_unit": product_unit,
                    }
                )
                display = self._product_line(item, qty=product_qty, unit=product_unit)
                # Stable 0-based index for Product tabs (stored indices can collide).
                display["product_index"] = index
                display["display_number"] = index + 1
                product_serial = _product_base_serial(
                    item,
                    parent_serial=serial,
                    rows_by_id=rows_by_id,
                    serial_key=serial_key,
                )
                # BOQ Description = the Unit/Qty row text, not the section header above it.
                qty_description = _qty_row_description(
                    group,
                    item,
                    product_index=index,
                    fallback=description or line_description,
                )
                display["line_key"] = f"{row_id}:{index}"
                display["row_id"] = row_id
                # Keep Unit/Qty slot identity for BOQ export Rate/Amount placement.
                display["qty_row_id"] = item.get("qty_row_id") or item.get("source_row_id")
                display["source_row_id"] = item.get("source_row_id") or item.get("qty_row_id")
                display["serial"] = product_serial
                display["depth"] = depth
                display["description"] = qty_description
                display["qty"] = product_qty
                display["unit"] = product_unit
                display.update(qty_fields)
                display["review_output"] = build_review_output_row(
                    serial=product_serial,
                    description=qty_description,
                    product=item,
                    selected=display.get("selected") or {},
                    rate_detail=display.get("rate_detail"),
                    line_output=display.get("line_output") or {},
                    qty=product_qty,
                )
                if display.get("status") == "matched":
                    matched_count += 1
                elif display.get("status") in {"pending", "unmatched", "not_searched"}:
                    pending_count += 1
                products.append(display)

            _assign_export_serials(products)

            if products:
                product_statuses = [
                    str(product.get("status") or "") for product in products
                ]
                if any(
                    status in {"unmatched", "pending", "not_searched"}
                    for status in product_statuses
                ):
                    line_status = "no_match"
                elif product_statuses and all(
                    status == "matched" for status in product_statuses
                ):
                    line_status = "matched"
                else:
                    line_status = "default"
            else:
                line_status = "default"
            if not analysis_row:
                line_status = "default"

            first = products[0] if products else {}
            lines.append(
                {
                    "row_id": row_id,
                    "serial": serial,
                    "depth": depth,
                    "description": line_description,
                    "full_description": full_description,
                    "lineage_parts": lineage_parts,
                    "lineage_count": lineage_count,
                    "qty": first.get("quantity", qty),
                    "unit": first.get("quantity_unit", unit),
                    "qty_display": first.get("quantity_display")
                    or (str(qty) if qty not in (None, "") else "—"),
                    "unit_display": first.get("quantity_unit_display")
                    or (str(unit).strip() if unit not in (None, "") else "—"),
                    "show_qty_unit": bool(first.get("show_quantity"))
                    or qty not in (None, "")
                    or bool(unit),
                    "status": line_status,
                    "products": products,
                    "product_count": len(products),
                }
            )

        labour_config = analysis.get("labour_config") or {}
        has_vendor = any(
            (row.get("products") or [])
            for row in (analysis.get("rows") or [])
        )
        return {
            "has_analysis": bool(analysis.get("rows")) and has_vendor,
            "stats": {
                "products_total": product_total,
                "products_matched": matched_count,
                "products_pending": pending_count,
                **(analysis.get("stats") or {}),
            },
            "confirmation_stats": {
                "confirmed_count": 0,
                "pending_count": pending_count,
            },
            "labour_mode": labour_config.get("mode") or "",
            "labour_ready": bool(labour_config.get("labour_ready")),
            "pricing_ready": bool(analysis.get("pricing_ready")),
            "review_headers": REVIEW_UI_HEADERS,
            "lines": lines,
        }

    def _product_line(
        self,
        product: dict[str, Any],
        *,
        qty: Any,
        unit: Any,
    ) -> dict[str, Any]:
        selection = dict(product.get("vendor_selection") or {})
        rate_detail = selection.get("rate_detail")
        labour_detail = selection.get("labour_detail")
        line_output = selection.get("line_output") or {}
        status = str(selection.get("status") or "not_searched")
        confidence = float(selection.get("confidence") or 0)

        selected = {
            "rate_master_id": selection.get("rate_master_id")
            or (rate_detail or {}).get("rate_master_id"),
            "product_id": selection.get("product_id")
            or (rate_detail or {}).get("product_id"),
            "rate_id": selection.get("rate_id")
            or (rate_detail or {}).get("rate_id"),
            "tech_key": selection.get("tech_key")
            or (rate_detail or {}).get("product_display_key")
            or (rate_detail or {}).get("tech_key")
            or "",
            "make": selection.get("make")
            or product.get("selected_make")
            or (rate_detail or {}).get("make")
            or "",
            "vendor": selection.get("vendor")
            or product.get("selected_vendor")
            or (rate_detail or {}).get("vendor")
            or "",
            "category": product.get("category")
            or (rate_detail or {}).get("category")
            or "",
            "sub_category": product.get("sub_category")
            or (rate_detail or {}).get("sub_category")
            or "",
        }

        return {
            "product_index": int(product.get("product_index") or 0),
            "status": status,
            "is_confirmed": False,
            "confidence": confidence,
            "extracted_category": product.get("category"),
            "extracted_sub_category": product.get("sub_category"),
            "summary": _product_summary(product),
            "selected": selected,
            "rate_detail": rate_detail,
            "labour_detail": labour_detail,
            "line_output": line_output,
            "labour_mode": product.get("labour_mode") or "",
            "labour_percent": product.get("labour_percent"),
            "candidates": [],
            "notes": selection.get("notes") or "",
            "approved_makes_applied": None,
            "confirmed_rate_master_id": None,
        }
