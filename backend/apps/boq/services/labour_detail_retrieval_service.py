"""Read precomputed Labour_Master values linked by Tech_Key."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.database_manager.models import Labour_Master

# Workbook column → snapshot key mapping for labour charge components.
LABOUR_CHARGE_COLUMN_MAP: tuple[tuple[str, str], ...] = (
    ("labour_rate_per_unit", "Labour_Rate_Per_unit"),
    ("testing_labour_value", "Testing_Labour_Value"),
    ("scaffolding_labour_value", "Scaffolding_Labour_Value"),
    ("consumables_labour_value", "Consumables_Labour_Value"),
    ("painting_labour_value", "Painting_Labour_Value"),
    ("labour_buffer_value", "Labour_Buffer_Value"),
    ("total_labour_per_unit", "Total_Labour_per_Unit"),
    ("labour_multiplier", "Labour_Multiplier"),
    ("total_labour_per_unit_with_multiplier", "Total_Labour_per_unit_with_labour_Multipler"),
)


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _model_value(row: Labour_Master, model_field: str) -> str | None:
    return _decimal(getattr(row, model_field, None))


def gather_labour_charges(row: Labour_Master) -> dict[str, Any]:
    """Gather labour charge components from the correct Labour_Master columns."""
    components: dict[str, str | None] = {}
    for snapshot_key, model_field in LABOUR_CHARGE_COLUMN_MAP:
        components[snapshot_key] = _model_value(row, model_field)

    effective = (
        components.get("total_labour_per_unit_with_multiplier")
        or components.get("total_labour_per_unit")
        or components.get("labour_rate_per_unit")
    )

    return {
        "components": components,
        "effective_labour_rate": effective,
    }


def labour_to_snapshot(row: Labour_Master) -> dict[str, Any]:
    """Return a JSON-safe snapshot of one Labour_Master row."""
    charges = gather_labour_charges(row)
    return {
        "labour_master_id": row.pk,
        "tech_key": row.Tech_Key,
        "size": _decimal(row.Size),
        "labour_type": row.Labour_Type,
        "base_rate": _decimal(row.Base_Rate),
        "size_factor": _decimal(row.Size_Factor),
        **charges["components"],
        "effective_labour_rate": charges["effective_labour_rate"],
        "charges": charges,
    }


class LabourDetailRetrievalService:
    """Fetch Labour_Master rows for a Tech_Key from the active database."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id

    def get_by_tech_key(
        self,
        tech_key: str | None,
        *,
        size: Decimal | float | str | None = None,
    ) -> dict[str, Any] | None:
        if not tech_key:
            return None

        queryset = Labour_Master.objects.filter(
            Tech_Key=tech_key,
            database_version_id=self.database_version_id,
        )
        rows = list(queryset)
        if not rows:
            return None

        matched = self._pick_row(rows, size=size)
        return labour_to_snapshot(matched)

    def get_all_by_tech_key(self, tech_key: str | None) -> list[dict[str, Any]]:
        if not tech_key:
            return []
        rows = Labour_Master.objects.filter(
            Tech_Key=tech_key,
            database_version_id=self.database_version_id,
        )
        return [labour_to_snapshot(row) for row in rows]

    @staticmethod
    def _pick_row(
        rows: list[Labour_Master],
        *,
        size: Decimal | float | str | None,
    ) -> Labour_Master:
        if len(rows) == 1:
            return rows[0]

        if size is not None:
            try:
                target = Decimal(str(size))
            except Exception:  # noqa: BLE001
                target = None
            if target is not None:
                for row in rows:
                    if row.Size is not None and row.Size == target:
                        return row

        return rows[0]
