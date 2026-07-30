"""Shape analysis + session confirmations for BOQ detail templates."""
from __future__ import annotations

from typing import Any

from apps.boq.models import BOQ
from apps.boq.services.boq_confirmation_service import resolve_confirmed_line
from apps.boq.services.make_list_constraint_service import walk_rows_tree
from apps.boq.services.serial_normalizer import analysis_fields
from common.constants import MATCH_CONFIDENCE_THRESHOLD

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
    """Return BOQ rows in the same order as the uploaded sheet."""
    flat_rows = boq_data.get("rows") or []
    if flat_rows:
        return flat_rows
    return walk_rows_tree(boq_data.get("rows_tree") or [])


def _line_key(row_id: str, product_index: int) -> str:
    return f"{row_id}:{product_index}"


class BOQAnalysisDisplayService:
    """Merge auto analysis with session confirmations for UI and export."""

    def __init__(self, boq: BOQ, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq = boq
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
        confirmed_count = 0
        pending_count = 0

        for boq_row in _ordered_boq_rows(boq_data):
            row_id = str(boq_row.get("row_id") or "")
            if not row_id:
                continue

            analysis_row = analysis_by_row.get(row_id, {})
            # Lineage children are consolidated onto anchors — hide empty stubs.
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
            for item in analysis_row.get("product_matches") or []:
                product_index = int(item.get("product_index") or 0)
                key = _line_key(row_id, product_index)
                confirmation = self.confirmations.get(key)
                display = self._product_line(item, confirmation)
                display["line_key"] = key
                display["row_id"] = row_id
                display["serial"] = serial
                display["depth"] = depth
                display["description"] = description
                display["qty"] = qty or ((item.get("extracted") or {}).get("quantity"))
                display["unit"] = unit or ((item.get("extracted") or {}).get("quantity_unit"))
                if display.get("is_confirmed"):
                    confirmed_count += 1
                elif display.get("status") == "pending":
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

        stats = analysis.get("stats") or {}
        phase = analysis.get("phase")
        has_matches = phase == "matched" or any(
            (row.get("product_matches") or [])
            for row in (analysis.get("rows") or [])
        )
        return {
            "has_analysis": bool(analysis.get("rows")) and has_matches,
            "stats": stats,
            "confirmation_stats": {
                "confirmed_count": confirmed_count,
                "pending_count": pending_count,
            },
            "lines": lines,
        }

    def _product_line(
        self,
        item: dict[str, Any],
        confirmation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        match = item.get("match") or {}
        extracted = item.get("extracted") or {}
        candidates = match.get("candidates") or []
        confidence = float(match.get("confidence") or 0)

        resolved = resolve_confirmed_line(self.boq.pk, item, confirmation)
        rate_detail = resolved.get("rate_detail")
        labour_detail = resolved.get("labour_detail")
        line_output = resolved.get("line_output") or {}
        status = resolved.get("status") or "pending"
        is_confirmed = bool(resolved.get("confirmed"))

        if not is_confirmed:
            if match.get("status") == "matched" and confidence >= MATCH_CONFIDENCE_THRESHOLD:
                status = "matched"
            else:
                status = "pending"
            rate_detail = item.get("rate_detail")
            labour_detail = item.get("labour_detail")
            line_output = item.get("line_output") or {}

        selected = None
        if rate_detail:
            selected = {
                "rate_master_id": rate_detail.get("rate_master_id"),
                "tech_key": rate_detail.get("tech_key"),
                "make": rate_detail.get("make"),
                "supplier": rate_detail.get("supplier"),
                "category": rate_detail.get("category"),
                "sub_category": rate_detail.get("sub_category"),
            }

        return {
            "product_index": item.get("product_index", 0),
            "status": status,
            "is_confirmed": is_confirmed,
            "confidence": confidence,
            "extracted_category": extracted.get("category"),
            "extracted_sub_category": extracted.get("sub_category"),
            "selected": selected,
            "rate_detail": rate_detail,
            "labour_detail": labour_detail,
            "line_output": line_output,
            "candidates": candidates,
            "approved_makes_applied": match.get("approved_makes_applied"),
            "confirmed_rate_master_id": (confirmation or {}).get("rate_master_id"),
        }
