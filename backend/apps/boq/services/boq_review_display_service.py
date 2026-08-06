"""Shape Make & Vendor + Labour product lines for Review and export."""
from __future__ import annotations

from typing import Any

from apps.boq.models import BOQ
from apps.boq.services.make_list_constraint_service import walk_rows_tree
from apps.boq.services.serial_normalizer import analysis_fields

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_UNIT_KEYS = ("unit", "uom")

# Client Output format.xlsx column labels (Review sheet / Review tab).
REVIEW_OUTPUT_HEADERS = [
    "Ser no of BOQ",
    "BOQ Description",
    "AI based Interpretation of BOQ Item",
    "Matching Rate_ID (column A) in Rate_Master_Output Sheet",
    "Make  (column J) in Rate_Master_Output Sheet",
    "Vendor  (column K) in Rate_Master_Output Sheet",
    "Base_Purchase_Rate  (column L) in Rate_Master_Output Sheet",
    "Discount  (column N) in Rate_Master_Output Sheet",
    "Net_Material_Rate  (column O) in Rate_Master_Output Sheet",
    "Procurement_Value  (column P) in Rate_Master_Output Sheet",
    "Commercial_Material_Base  (column Q) in Rate_Master_Output Sheet",
    "Accessories_Value  (column R) in Rate_Master_Output Sheet",
    "Handling_Value  (column S) in Rate_Master_Output Sheet",
    "Wastage_Value  (column T) in Rate_Master_Output Sheet",
    "Sub_Total  (column U) in Rate_Master_Output Sheet",
    "Profit_Value  (column V) in Rate_Master_Output Sheet",
    "Final_Material_Amount  (column W) in Rate_Master_Output Sheet",
    "Labour (Colmn R ) in Labour_Master_Output Sheet",
    "Qty (as in BOQ)",
    "TOTAL MATERIAL (Q*S)",
    "TOTAL LABOUR (R*S)",
    "Amount (T+U)",
]

# Shorter labels for the on-screen Review table (same column order).
REVIEW_UI_HEADERS = [
    "Ser no",
    "BOQ Description",
    "AI Interpretation",
    "Rate_ID",
    "Make",
    "Vendor",
    "Base Purchase Rate",
    "Discount",
    "Net Material Rate",
    "Procurement",
    "Commercial Material Base",
    "Accessories",
    "Handling",
    "Wastage",
    "Sub Total",
    "Profit",
    "Final Material Amount",
    "Labour",
    "Qty",
    "TOTAL MATERIAL",
    "TOTAL LABOUR",
    "Amount",
]


def _field_from_map(fields: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return value
    return None


def _ordered_boq_rows(boq_data: dict) -> list[dict[str, Any]]:
    flat_rows = boq_data.get("rows") or []
    if flat_rows:
        return flat_rows
    return walk_rows_tree(boq_data.get("rows_tree") or [])


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

        lines: list[dict[str, Any]] = []
        matched_count = 0
        pending_count = 0
        product_total = 0

        for boq_row in _ordered_boq_rows(boq_data):
            row_id = str(boq_row.get("row_id") or "")
            if not row_id:
                continue

            analysis_row = analysis_by_row.get(row_id, {})
            if analysis_row.get("skip_reason") == "lineage_child_row":
                continue

            fields = analysis_fields(boq_row)
            serial = boq_row.get("serial", "")
            depth = boq_row.get("depth", 0)
            description = _field_from_map(fields, _DESCRIPTION_KEYS) or ""
            qty = _field_from_map(fields, _QTY_KEYS)
            unit = _field_from_map(fields, _UNIT_KEYS)

            if analysis_row.get("skip_matching"):
                lines.append(
                    {
                        "row_id": row_id,
                        "serial": serial,
                        "depth": depth,
                        "description": description,
                        "qty": qty,
                        "unit": unit,
                        "status": "skipped",
                        "products": [],
                    }
                )
                continue

            products: list[dict[str, Any]] = []
            for item in analysis_row.get("products") or []:
                product_total += 1
                display = self._product_line(item, qty=qty, unit=unit)
                display["line_key"] = f"{row_id}:{display['product_index']}"
                display["row_id"] = row_id
                display["serial"] = serial
                display["depth"] = depth
                display["description"] = description
                display["qty"] = qty or item.get("quantity")
                display["unit"] = unit or item.get("quantity_unit")
                display["review_output"] = build_review_output_row(
                    serial=serial,
                    description=description,
                    product=item,
                    selected=display.get("selected") or {},
                    rate_detail=display.get("rate_detail"),
                    line_output=display.get("line_output") or {},
                    qty=display["qty"],
                )
                if display.get("status") == "matched":
                    matched_count += 1
                elif display.get("status") in {"pending", "unmatched", "not_searched"}:
                    pending_count += 1
                products.append(display)

            line_status = "active" if products else "empty"
            if not analysis_row:
                line_status = "not_analyzed"

            lines.append(
                {
                    "row_id": row_id,
                    "serial": serial,
                    "depth": depth,
                    "description": description,
                    "qty": qty,
                    "unit": unit,
                    "status": line_status,
                    "products": products,
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
