"""Calculate final row prices after Labour and mark BOQ ready to export."""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction

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


def build_row_pricing(display: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Aggregate priced output per BOQ row for the original sheet."""
    pricing: dict[str, dict[str, Any]] = {}
    for line in display.get("lines") or []:
        row_id = str(line.get("row_id") or "")
        if not row_id:
            continue

        material_total = Decimal("0")
        labour_total = Decimal("0")
        total_amount = Decimal("0")
        has_values = False

        for product in line.get("products") or []:
            line_output = product.get("line_output") or {}
            if line_output.get("is_blank"):
                continue
            material_amount = _to_decimal(line_output.get("material_amount"))
            labour_amount = _to_decimal(line_output.get("labour_amount"))
            row_total = _to_decimal(line_output.get("total_amount"))
            if material_amount is not None:
                material_total += material_amount
                has_values = True
            if labour_amount is not None:
                labour_total += labour_amount
                has_values = True
            if row_total is not None:
                total_amount += row_total
                has_values = True

        if not has_values:
            continue

        qty = _to_decimal(line.get("qty"))
        unit_rate = None
        if qty and qty != 0:
            unit_rate = total_amount / qty

        pricing[row_id] = {
            "rate": _format_decimal(unit_rate),
            "amount": _format_decimal(total_amount),
            "material_amount": _format_decimal(material_total),
            "labour_amount": _format_decimal(labour_total),
        }
    return pricing


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

        with transaction.atomic():
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
