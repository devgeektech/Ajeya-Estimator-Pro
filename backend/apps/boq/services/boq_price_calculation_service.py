"""Calculate final row prices after Labour and mark BOQ ready to export."""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from common.db import atomic

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_store import save_boq_analysis_json
from apps.boq.services.boq_review_display_service import BOQReviewDisplayService
from common.choices import BOQStatus
from common.exceptions import BOQAIError, ValidationError
from utils.json_safe import json_safe
from utils.timestamps import now_local_iso

logger = logging.getLogger("boq_ai")


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _format_decimal(value: Decimal | None) -> Any:
    if value is None:
        return None
    return float(value)


_UNMATCHED_STATUSES = frozenset({"unmatched", "pending", "not_searched", "no_match"})


def _product_target_row_id(product: dict[str, Any], line: dict[str, Any]) -> str:
    """BOQ sheet row that should receive this product's Rate/Amount."""
    target = str(
        product.get("qty_row_id") or product.get("source_row_id") or ""
    ).strip()
    if target:
        return target
    # Single-product lines sometimes only carry qty on the parent analysis row.
    products = line.get("products") or []
    if len(products) == 1:
        return str(line.get("row_id") or "").strip()
    return ""


def build_row_pricing(display: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map priced output onto each product's Unit/Qty BOQ row (not the section)."""
    pricing: dict[str, dict[str, Any]] = {}
    for line in display.get("lines") or []:
        for product in line.get("products") or []:
            target_row_id = _product_target_row_id(product, line)
            if not target_row_id:
                continue

            line_output = product.get("line_output") or {}
            if line_output.get("is_blank"):
                continue
            status = str(product.get("status") or "").strip().lower()
            if status in _UNMATCHED_STATUSES:
                continue

            material_amount = _to_decimal(line_output.get("material_amount"))
            labour_amount = _to_decimal(line_output.get("labour_amount"))
            row_total = _to_decimal(line_output.get("total_amount"))
            if material_amount is None and labour_amount is None and row_total is None:
                continue

            existing = pricing.get(target_row_id)
            material_total = _to_decimal((existing or {}).get("material_amount")) or Decimal("0")
            labour_total = _to_decimal((existing or {}).get("labour_amount")) or Decimal("0")
            total_amount = _to_decimal((existing or {}).get("amount")) or Decimal("0")

            if material_amount is not None:
                material_total += material_amount
            if labour_amount is not None:
                labour_total += labour_amount
            if row_total is not None:
                total_amount += row_total
            elif material_amount is not None or labour_amount is not None:
                total_amount += (material_amount or Decimal("0")) + (
                    labour_amount or Decimal("0")
                )

            qty = _to_decimal(
                product.get("qty")
                if product.get("qty") not in (None, "")
                else line_output.get("quantity")
            )
            unit_rate = None
            if qty and qty != 0:
                unit_rate = total_amount / qty

            pricing[target_row_id] = {
                "rate": _format_decimal(unit_rate),
                "amount": _format_decimal(total_amount),
                "material_amount": _format_decimal(material_total),
                "labour_amount": _format_decimal(labour_total),
            }
    return pricing


def unmatched_qty_row_ids(
    display: dict[str, Any],
    *,
    boq_data: dict[str, Any] | None = None,
) -> set[str]:
    """Unit/Qty row ids with no fetched/matched product (for export highlight)."""
    from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows

    matched_ids: set[str] = set()
    highlight_ids: set[str] = set()

    for line in display.get("lines") or []:
        for product in line.get("products") or []:
            target_row_id = _product_target_row_id(product, line)
            if not target_row_id:
                continue
            line_output = product.get("line_output") or {}
            status = str(product.get("status") or "").strip().lower()
            if status == "matched" and not line_output.get("is_blank"):
                matched_ids.add(target_row_id)
            else:
                highlight_ids.add(target_row_id)

    for group in grouped_anchor_rows(boq_data or {}):
        for slot in group.get("slots") or group.get("qty_rows") or []:
            slot_id = str(slot.get("qty_row_id") or slot.get("row_id") or "").strip()
            if not slot_id or slot_id in matched_ids:
                continue
            qty = slot.get("qty")
            unit = slot.get("unit")
            if qty in (None, "") and not unit:
                continue
            # Rate-only / zero qty slots still need a product when unit is present.
            if unit in (None, "") and qty in (None, ""):
                continue
            highlight_ids.add(slot_id)

    return highlight_ids


class BOQPriceCalculationService:
    """Persist final prices mapped to original BOQ rows; unlock export."""

    def __init__(self, boq_id: int, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq_id = boq_id
        self.confirmations = confirmations or {}

    def run(self) -> dict[str, Any]:
        try:
            boq = BOQ.objects.get(pk=self.boq_id)
        except BOQ.DoesNotExist as exc:
            raise BOQAIError(f"BOQ id={self.boq_id} not found.") from exc

        if boq.status == BOQStatus.MATCHING:
            raise ValidationError("Wait for the current job to finish before calculating prices.")
        if boq.status not in {
            BOQStatus.LABOUR,
            BOQStatus.PROCESSED,
            BOQStatus.READY_EXPORT,
            BOQStatus.EXPORTED,
        }:
            raise ValidationError("Apply labour on the Labour tab before continuing.")

        analysis = boq.analysis_data or {}
        if not (analysis.get("labour_config") or {}).get("labour_ready"):
            raise ValidationError("Apply Auto or Manual labour before continuing.")

        display = BOQReviewDisplayService(boq, self.confirmations).build()
        if not display.get("has_analysis"):
            raise ValidationError("No Make & Vendor products available to price.")

        row_pricing = build_row_pricing(display)
        analysis = dict(analysis)
        analysis["pricing_ready"] = True
        analysis["row_pricing"] = row_pricing
        analysis["pricing_calculated_at"] = now_local_iso()

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.status = BOQStatus.READY_EXPORT
            boq.save(update_fields=["analysis_data", "status"])

        logger.info(
            "BOQ prices calculated id=%s rows_priced=%s",
            boq.pk,
            len(row_pricing),
        )
        return {
            "row_count": len(row_pricing),
            "pricing_ready": True,
            "status": BOQStatus.READY_EXPORT,
        }
