"""Read precomputed Rate_Master_Output values for matched BOQ lines."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.database_manager.models import Rate_Master_Output


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def rate_to_snapshot(rate: Rate_Master_Output) -> dict[str, Any]:
    """Return a JSON-safe snapshot of one Rate_Master_Output row."""
    return {
        "rate_master_id": rate.pk,
        "rate_id": rate.Rate_ID,
        "product_id": rate.Product_ID,
        "product_display_key": rate.display_key(),
        # Legacy analysis key used as display label in some UI paths.
        "tech_key": rate.display_key(),
        "category": rate.Category,
        "sub_category": rate.Sub_Category,
        "class": rate.Class,
        "size": _decimal(rate.Size),
        "make": rate.Make,
        "capacity": rate.Capacity,
        "unit": rate.Unit,
        "attribute": rate.Attribute,
        "vendor": rate.Vendor,
        "base_purchase_rate": _decimal(rate.Base_Purchase_Rate),
        "discount": _decimal(rate.Discount),
        "net_material_rate": _decimal(rate.Net_Material_Rate),
        "procurement_value": _decimal(rate.Procurement_Value),
        "commercial_material_base": _decimal(rate.Commercial_Material_Base),
        "accessories_value": _decimal(rate.Accessories_Value),
        "handling_value": _decimal(rate.Handling_Value),
        "wastage_value": _decimal(rate.Wastage_Value),
        "sub_total": _decimal(rate.Sub_Total),
        "profit_value": _decimal(rate.Profit_Value),
        "final_material_amount": _decimal(rate.Final_Material_Amount),
        "margin_pct_on_selling": _decimal(rate.Margin_pct_on_Selling),
        # Pricing amount used by Make & Vendor / export.
        "selection_amount": _decimal(rate.Final_Material_Amount),
    }


class RateDetailRetrievalService:
    """Fetch Rate_Master_Output snapshots by primary key."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id

    def get_by_id(self, rate_master_id: int) -> dict[str, Any] | None:
        rate = (
            Rate_Master_Output.objects.filter(
                pk=rate_master_id,
                database_version_id=self.database_version_id,
            )
            .first()
        )
        if rate is None:
            return None
        return rate_to_snapshot(rate)

    def get_many_by_ids(self, rate_master_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not rate_master_ids:
            return {}
        rows = Rate_Master_Output.objects.filter(
            pk__in=rate_master_ids,
            database_version_id=self.database_version_id,
        )
        return {row.pk: rate_to_snapshot(row) for row in rows}
