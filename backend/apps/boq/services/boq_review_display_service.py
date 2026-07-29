"""Shape Make & Vendor + Labour product lines for Review and export."""
from __future__ import annotations

from typing import Any

from apps.boq.models import BOQ
from apps.boq.services.make_list_constraint_service import walk_rows_tree
from apps.boq.services.serial_normalizer import analysis_fields

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_UNIT_KEYS = ("unit", "uom")


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
            "tech_key": selection.get("tech_key")
            or (rate_detail or {}).get("tech_key")
            or "",
            "make": selection.get("make")
            or product.get("selected_make")
            or (rate_detail or {}).get("make")
            or "",
            "supplier": selection.get("supplier")
            or product.get("selected_supplier")
            or (rate_detail or {}).get("supplier")
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
