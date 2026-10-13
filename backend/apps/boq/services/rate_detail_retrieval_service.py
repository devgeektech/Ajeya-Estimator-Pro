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

    def __init__(self, database_version_id: int | None = None):
        from apps.database_manager.services.activation import (
            resolve_active_database_version_id,
        )

        self.database_version_id = resolve_active_database_version_id(database_version_id)

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

    def get_by_rate_id(self, rate_id: str | int | None) -> dict[str, Any] | None:
        """Fetch Rate_Master_Output snapshot by workbook Rate_ID in the active DB."""
        if rate_id in (None, ""):
            return None
        from apps.database_manager.services.importer import _to_optional_id

        norm_id = _to_optional_id(rate_id)
        if not norm_id:
            return None
        rate = Rate_Master_Output.objects.filter(
            Rate_ID=norm_id,
            database_version_id=self.database_version_id,
        ).first()
        if rate is None and str(rate_id).strip() != norm_id:
            rate = Rate_Master_Output.objects.filter(
                Rate_ID=str(rate_id).strip(),
                database_version_id=self.database_version_id,
            ).first()
        if rate is None:
            return None
        return rate_to_snapshot(rate)

    def get_by_product_make_vendor(
        self,
        product_id: str | int | None,
        make: str = "",
        vendor: str = "",
    ) -> dict[str, Any] | None:
        """Fetch Rate_Master_Output snapshot by Product_ID + Make + Vendor."""
        if product_id in (None, ""):
            return None
        from apps.database_manager.services.importer import _to_optional_id

        norm_pid = _to_optional_id(product_id)
        if not norm_pid:
            return None
        qs = Rate_Master_Output.objects.filter(
            Product_ID=norm_pid,
            database_version_id=self.database_version_id,
        )
        make_str = str(make or "").strip()
        vendor_str = str(vendor or "").strip()
        if make_str and vendor_str:
            rate = qs.filter(Make__iexact=make_str, Vendor__iexact=vendor_str).first()
            if rate is not None:
                return rate_to_snapshot(rate)
        if make_str:
            rate = qs.filter(Make__iexact=make_str).first()
            if rate is not None:
                return rate_to_snapshot(rate)
        rate = qs.order_by("Final_Material_Amount").first()
        if rate is not None:
            return rate_to_snapshot(rate)
        return None

    def resolve_rate_detail(
        self,
        *,
        rate_master_id: int | str | None = None,
        rate_id: str | int | None = None,
        product_id: str | int | None = None,
        make: str | None = None,
        vendor: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Resolve the active Rate_Master_Output snapshot using available identifiers.

        Tries primary key first, falls back to Rate_ID, then Product_ID + Make + Vendor.
        """
        if rate_master_id:
            try:
                res = self.get_by_id(int(rate_master_id))
                if res:
                    return res
            except (TypeError, ValueError):
                pass
        if rate_id:
            res = self.get_by_rate_id(rate_id)
            if res:
                return res
        if product_id:
            res = self.get_by_product_make_vendor(
                product_id,
                make=make or "",
                vendor=vendor or "",
            )
            if res:
                return res
        return None
