"""Build priced line output from precomputed master values (no formula recalculation)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _format_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _is_rate_only_quantity(quantity: Any) -> bool:
    if quantity in (None, ""):
        return False
    text = str(quantity).strip().lower()
    return text in {"rate only", "ro", "r.o", "r.o."} or text.startswith("rate only")


def quantity_is_rate_sum_only(quantity: Any, *, rate_only: bool = False) -> bool:
    """
    True when Review/Export should show material_rate + labour_rate (not × qty).

    Applies for explicit qty ``0`` and Rate Only / RO slots.
    """
    if rate_only or _is_rate_only_quantity(quantity):
        return True
    qty = _to_decimal(quantity)
    return qty is not None and qty == 0


class BOQLineOutputService:
    """Combine BOQ quantity with rate and labour output snapshots."""

    @staticmethod
    def build(
        *,
        quantity: Any,
        rate_detail: dict[str, Any] | None,
        labour_detail: dict[str, Any] | None,
        is_pending: bool,
        rate_only: bool = False,
    ) -> dict[str, Any]:
        """Return display/export values for one product line."""
        if is_pending or not rate_detail:
            return {
                "quantity": quantity,
                "material_rate": None,
                "labour_rate": None,
                "material_amount": None,
                "labour_amount": None,
                "total_amount": None,
                "is_blank": True,
                "amount_is_rate_sum": False,
            }

        qty = _to_decimal(quantity)
        # Product rate is always Rate_Master Final_Material_Amount.
        material_rate = _to_decimal(rate_detail.get("final_material_amount"))
        if material_rate is None:
            material_rate = _to_decimal(rate_detail.get("selection_amount"))
        labour_rate = _to_decimal(
            labour_detail.get("effective_labour_rate") if labour_detail else None
        )
        labour_components = {}
        if labour_detail:
            labour_components = dict((labour_detail.get("charges") or {}).get("components") or {})
            if not labour_components:
                labour_components = {
                    key: labour_detail.get(key)
                    for key, _ in (
                        ("labour_rate_per_unit", ""),
                        ("testing_labour_value", ""),
                        ("scaffolding_labour_value", ""),
                        ("consumables_labour_value", ""),
                        ("painting_labour_value", ""),
                        ("labour_buffer_value", ""),
                        ("total_labour_per_unit", ""),
                        ("labour_multiplier", ""),
                        ("total_labour_per_unit_with_multiplier", ""),
                    )
                    if labour_detail.get(key) is not None
                }

        # Normal: (material_rate + labour_rate) × qty via separate amounts.
        # Qty 0 / Rate Only / RO: show sum of unit rates only (no quantity multiply).
        use_rate_sum = quantity_is_rate_sum_only(quantity, rate_only=rate_only)
        if use_rate_sum:
            material_amount = material_rate
            labour_amount = labour_rate
        else:
            material_amount = qty * material_rate if qty is not None and material_rate else None
            labour_amount = qty * labour_rate if qty is not None and labour_rate else None

        total_amount = None
        if material_amount is not None or labour_amount is not None:
            total_amount = (material_amount or Decimal("0")) + (labour_amount or Decimal("0"))

        return {
            "quantity": quantity,
            "material_rate": _format_decimal(material_rate),
            "labour_rate": _format_decimal(labour_rate),
            "labour_components": labour_components,
            "material_amount": _format_decimal(material_amount),
            "labour_amount": _format_decimal(labour_amount),
            "total_amount": _format_decimal(total_amount),
            "is_blank": False,
            "amount_is_rate_sum": use_rate_sum,
        }
