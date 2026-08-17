"""Read precomputed Labour_master_Output values linked by Product_ID."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.database_manager.models import Labour_master_Output

# Workbook column → snapshot key mapping for labour charge components.
LABOUR_CHARGE_COLUMN_MAP: tuple[tuple[str, str], ...] = (
    ("labour_rate_per_unit", "Labour_Rate_Per_unit"),
    ("testing_labour_value", "Testing_Labour_Value"),
    ("scaffolding_labour_value", "Scaffolding_Labour_Value"),
    ("consumables_labour_value", "Consumables_Labour_Value"),
    ("painting_labour_value", "Painting_Labour_Value"),
    ("labour_buffer_value", "Labour_Buffer_Value"),
    ("total_labour_per_unit", "Total_Labour_per_Unit"),
    (
        "total_labour_per_unit_with_multiplier",
        "Total_Labour_per_unit_with_labour_Multipler",
    ),
)


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _model_value(row: Labour_master_Output, model_field: str) -> str | None:
    return _decimal(getattr(row, model_field, None))


def gather_labour_charges(row: Labour_master_Output) -> dict[str, Any]:
    """Gather labour charge components from Labour_master_Output columns."""
    components: dict[str, str | None] = {}
    for snapshot_key, model_field in LABOUR_CHARGE_COLUMN_MAP:
        components[snapshot_key] = _model_value(row, model_field)

    # Preferred BOQ labour unit amount: Labour_With_State_Multiplier
    # (model Total_Labour_per_unit_with_labour_Multipler). Fall back to
    # Total_Labour_Per_Unit, then Labour_Rate_Per_unit when blank.
    effective = components.get("total_labour_per_unit_with_multiplier")
    if effective in (None, ""):
        effective = components.get("total_labour_per_unit")
    if effective in (None, ""):
        effective = components.get("labour_rate_per_unit")

    return {
        "components": components,
        "effective_labour_rate": effective,
    }


def labour_to_snapshot(row: Labour_master_Output) -> dict[str, Any]:
    """Return a JSON-safe snapshot of one Labour_master_Output row."""
    charges = gather_labour_charges(row)
    return {
        "labour_master_id": row.pk,
        "product_id": row.Product_ID,
        "product_display_key": row.display_key(),
        "tech_key": row.display_key(),
        "category": row.Category,
        "sub_category": row.Sub_Category,
        "class": row.Class,
        "size": _decimal(row.Size),
        "unit": row.Unit,
        "capacity": row.Capacity,
        "attribute": row.Attribute,
        "labour_type": row.Labour_Type,
        "base_rate": _decimal(row.Base_Rate),
        "size_factor": _decimal(row.Size_Factor),
        **charges["components"],
        "effective_labour_rate": charges["effective_labour_rate"],
        "charges": charges,
    }


class LabourDetailRetrievalService:
    """Fetch Labour_master_Output rows by Product_ID from the active database."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id

    def get_by_product_id(self, product_id: int | str | None) -> dict[str, Any] | None:
        if product_id in (None, ""):
            return None
        pid = str(product_id).strip()
        if not pid:
            return None
        row = Labour_master_Output.objects.filter(
            Product_ID=pid,
            database_version_id=self.database_version_id,
        ).first()
        if row is None:
            return None
        return labour_to_snapshot(row)
