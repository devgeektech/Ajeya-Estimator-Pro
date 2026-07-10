"""Database import service.

Implements the documented import workflow (docs/DATABASE.md):

Validate -> Backup -> Import -> Activate -> Generate Embeddings

The whole operation runs inside a single transaction so a failure leaves the
previously active database untouched. Embedding generation runs synchronously
after activation and never queues a Celery task.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction

from common.constants import DATABASE_UPLOADS_TO_RETAIN
from common.exceptions import ImportError_
from utils.excel import list_sheet_names, read_rows
from ai.context import clear_database_context_cache

from .activation import activate_database_version
from ..models import (
    DatabaseVersion,
    Labour_Master,
    Labour_Structure_Source,
    Rate_Master,
    State_Control_List,
    TOR_Accessories,
    TOR_Labour,
    TOR_Main,
)
from .validator import validate_workbook

logger = logging.getLogger("boq_ai")


def _to_decimal(value, default="0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _to_optional_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_optional_str(value) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    return text or None


def _to_str(value) -> str:
    return "" if value is None else str(value).strip()


def _row_value(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _stable_code_part(value) -> str:
    text = _to_str(value)
    if not text:
        return ""
    return "_".join(text.upper().replace("/", " ").replace("-", " ").split())


def _synth_rate_code(row: dict) -> str:
    parts = [
        row.get("category"),
        row.get("sub_category"),
        row.get("class"),
        _row_value(row, "size_mm", "size", "capacity", "head"),
    ]
    return "_".join(
        part for part in (_stable_code_part(value) for value in parts) if part
    )


def _discounted_rate(row: dict):
    rate = _row_value(
        row,
        "net_material_rate",
        "net_purchase_rate",
    )
    if rate not in (None, ""):
        return rate

    base_rate = row.get("base_purchase_rate")
    discount = _row_value(row, "discount", "discount_percent")
    if base_rate in (None, ""):
        return None
    base = _to_decimal(base_rate)
    if discount in (None, ""):
        return base
    discount_value = _to_decimal(discount)
    if discount_value:
        return base * (Decimal("1") - (discount_value / Decimal("100")))
    return base


def _final_amount(row: dict):
    value = _row_value(
        row, "final_amount_excl_gst", "final_amount", "final_expenditure"
    )
    if value not in (None, ""):
        return value
    return _discounted_rate(row)


def _state_control_fields(row: dict) -> dict:
    return {
        "State": _to_str(row.get("state")),
        "Labour_Multiplier": _to_optional_decimal(row.get("labour_multiplier")),
    }


# Per-sheet field extraction. Each builder receives a normalized row dict and
# returns model field kwargs (excluding the database_version FK).
def _rate_fields(row: dict) -> dict:
    tech_key = _to_str(row.get("tech_key")) or _synth_rate_code(row)
    net_material_rate = _to_optional_decimal(_discounted_rate(row))
    final_amount = _to_optional_decimal(_final_amount(row))
    return {
        "Tech_Key": tech_key,
        "Make": _to_optional_str(row.get("make")),
        "Final_Amount_Excl_GST": final_amount,
        "Unit": _to_optional_str(row.get("unit")),
        "Category": _to_optional_str(row.get("category")),
        "Sub_Category": _to_optional_str(row.get("sub_category")),
        "Class": _to_optional_str(row.get("class")),
        "Size": _to_optional_decimal(_row_value(row, "size_mm", "size")),
        "Capacity": _to_optional_str(row.get("capacity")),
        "Attribute": _to_optional_str(_row_value(row, "attribute", "attributes")),
        "Supplier": _to_optional_str(row.get("supplier")),
        "Base_Purchase_Rate": _to_optional_decimal(row.get("base_purchase_rate")),
        "Discount_Percent": _to_optional_decimal(
            _row_value(row, "discount_percent", "discount")
        ),
        "Net_Material_Rate": net_material_rate,
        "Procurement_Value": _to_optional_decimal(row.get("procurement_value")),
        "Commercial_Material_Base": _to_optional_decimal(
            row.get("commercial_material_base")
        ),
        "Accessories_Value": _to_optional_decimal(row.get("accessories_value")),
        "Handling_Value": _to_optional_decimal(row.get("handling_value")),
        "Wastage_Value": _to_optional_decimal(row.get("wastage_value")),
        "Subtotal_Before_Profit": _to_optional_decimal(row.get("subtotal_before_profit")),
        "Profit_Value": _to_optional_decimal(row.get("profit_value")),
        "Final_Expenditure": _to_optional_decimal(row.get("final_expenditure")),
        "Margin_Percent_On_Selling": _to_optional_decimal(
            _row_value(
                row,
                "margin_percent",
                "margin_percent_on_selling",
                "margin_on_selling",
            )
        ),
    }


def _labour_fields(row: dict) -> dict:
    tech_key = _to_str(row.get("tech_key")) or _synth_rate_code(row)

    return {
        "Tech_Key": tech_key,
        "Size": _to_optional_decimal(row.get("size")),
        "Labour_Type": _to_optional_str(row.get("labour_type")),
        "Base_Rate": _to_optional_decimal(row.get("base_rate")),
        "Size_Factor": _to_optional_decimal(row.get("size_factor")),
        "Labour_Rate_Per_unit": _to_optional_decimal(row.get("labour_rate_per_unit")),
        "Testing_Labour_Value": _to_optional_decimal(row.get("testing_labour_value")),
        "Scaffolding_Labour_Value": _to_optional_decimal(
            row.get("scaffolding_labour_value")
        ),
        "Consumables_Labour_Value": _to_optional_decimal(
            row.get("consumables_labour_value")
        ),
        "Painting_Labour_Value": _to_optional_decimal(row.get("painting_labour_value")),
        "Labour_Buffer_Value": _to_optional_decimal(row.get("labour_buffer_value")),
        "Total_Labour_per_Unit": _to_optional_decimal(row.get("total_labour_per_unit")),
        "Labour_Multiplier": _to_optional_decimal(row.get("labour_multiplier")),
        "Total_Labour_per_unit_with_labour_Multipler": _to_optional_decimal(
            _row_value(
                row,
                "total_labour_with_multiplier",
                "total_labour_per_unit_with_labour_multiplier",
            )
        ),
    }


def _tor_main_fields(row: dict) -> dict:
    return {
        "Category": _to_optional_str(row.get("category")),
        "Handling_Percent": _to_optional_decimal(
            _row_value(row, "handling_percent", "handling")
        ),
        "Wastage_Percent": _to_optional_decimal(
            _row_value(row, "wastage_percent", "wastage")
        ),
        "Profit_Percent": _to_optional_decimal(
            _row_value(row, "profit_percent", "profit")
        ),
        "Procurement_Percent": _to_optional_decimal(
            _row_value(row, "procurement_percent", "procurement")
        ),
        "Risk_Buffer_Percent": _to_optional_decimal(
            _row_value(row, "risk_buffer_percent", "risk_buffer")
        ),
        "Project_State": _to_optional_str(row.get("project_state")),
    }


def _labour_structure_fields(row: dict) -> dict:
    return {
        "Category": _to_optional_str(row.get("category")),
        "Sub_Category": _to_optional_str(row.get("sub_category")),
        "Size": _to_optional_decimal(row.get("size")),
        "Unit": _to_optional_str(row.get("unit")),
        "Tech_Key": _to_optional_str(row.get("tech_key")),
    }


def _tor_labour_fields(row: dict) -> dict:
    return {
        "Testing_Percent": _to_optional_decimal(
            _row_value(row, "testing_percent", "testing")
        ),
        "Scaffolding_Percent": _to_optional_decimal(
            _row_value(row, "scaffolding_percent", "scaffolding")
        ),
        "Consumables_Percent": _to_optional_decimal(
            _row_value(row, "consumables_percent", "consumables")
        ),
        "Painting_Rate": _to_optional_decimal(row.get("painting_rate")),
        "Labour_Buffer_Percent": _to_optional_decimal(
            _row_value(row, "labour_buffer_percent", "labour_buffer")
        ),
    }


def _tor_accessories_fields(row: dict) -> dict:
    return {
        "Category": _to_optional_str(row.get("category")),
        "Sub_Category": _to_optional_str(row.get("sub_category")),
        "Min_Size": _to_optional_decimal(row.get("min_size")),
        "Max_Size": _to_optional_decimal(row.get("max_size")),
        "Accessories_Percent": _to_optional_decimal(
            _row_value(row, "accessories_percent", "accessories")
        ),
    }


# Sheet name -> (model, field builder). These are version-scoped tables.
VERSIONED_SHEETS = {
    "Rate_Master": (Rate_Master, _rate_fields),
    "Labour_Master": (Labour_Master, _labour_fields),
    "TOR_Main": (TOR_Main, _tor_main_fields),
    "Labour_Structure_Source": (Labour_Structure_Source, _labour_structure_fields),
    "TOR_Labour": (TOR_Labour, _tor_labour_fields),
    "TOR_Accessories": (TOR_Accessories, _tor_accessories_fields),
    "State_Control_List": (State_Control_List, _state_control_fields),
}

REQUIRED_MODEL_FIELDS = {
    Rate_Master: ("Tech_Key", "Category"),
    Labour_Master: ("Tech_Key",),
    TOR_Main: ("Category",),
    Labour_Structure_Source: ("Tech_Key",),
    TOR_Labour: (),
    TOR_Accessories: ("Category", "Sub_Category"),
    State_Control_List: ("State",),
}


def _has_required_fields(model, fields: dict) -> bool:
    return all(
        _to_str(fields.get(field)) for field in REQUIRED_MODEL_FIELDS.get(model, ())
    )


class DatabaseImportService:
    """Orchestrates importing a master workbook into a new DatabaseVersion."""

    def __init__(
        self,
        file_path: str,
        uploaded_by,
        source_filename: str | None = None,
        version_name: str = "",
        stored_name: str = "",
    ):
        self.file_path = file_path
        self.uploaded_by = uploaded_by
        self.source_filename = source_filename or str(file_path)
        self.version_name = version_name
        self.stored_name = stored_name

    def run(self) -> DatabaseVersion:
        """Execute the full import workflow and return the activated version."""
        logger.info(
            "Database import started by %s", getattr(self.uploaded_by, "email", "?")
        )

        # 1. Validate structure before touching the database.
        validate_workbook(self.file_path)

        try:
            with transaction.atomic():
                version = self._create_version()
                self._import_versioned_sheets(version)
                self._activate(version)
            clear_database_context_cache()
            self._generate_embeddings(version)
            self._enforce_retention()
        except ImportError_:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Database import failed")
            raise ImportError_(f"Database import failed: {exc}") from exc

        logger.info("Database import completed: v%s", version.version_number)
        return version

    def _create_version(self) -> DatabaseVersion:
        last = DatabaseVersion.objects.order_by("-version_number").first()
        next_number = (last.version_number + 1) if last else 1
        return DatabaseVersion.objects.create(
            version_number=next_number,
            name=self.version_name,
            uploaded_by=self.uploaded_by,
            source_filename=self.source_filename,
            is_active=False,
            file=self.stored_name,
        )

    def _import_versioned_sheets(self, version: DatabaseVersion) -> None:
        available_sheets = set(list_sheet_names(self.file_path))
        for sheet_name, (model, builder) in VERSIONED_SHEETS.items():
            if sheet_name not in available_sheets:
                logger.info(
                    "Skipped %s: sheet not present in workbook", sheet_name
                )
                continue
            rows = read_rows(self.file_path, sheet_name)
            objects = []
            skipped = 0
            for row in rows:
                fields = builder(row)
                if not _has_required_fields(model, fields):
                    skipped += 1
                    continue
                objects.append(model(database_version=version, **fields))
            if objects:
                model.objects.bulk_create(objects, batch_size=500)
            logger.info(
                "Imported %s rows from %s (%s skipped)",
                len(objects),
                sheet_name,
                skipped,
            )

    def _generate_embeddings(self, version: DatabaseVersion) -> None:
        """Generate embeddings inline for the active Rate_Master rows."""
        from ai.embeddings.generator import generate_embeddings_for_version

        summary = generate_embeddings_for_version(version.pk)
        logger.info(
            "Embedding generation finished for v%s: %s", version.version_number, summary
        )

    def _activate(self, version: DatabaseVersion) -> None:
        activate_database_version(version)

    def _enforce_retention(self) -> None:
        """Keep only the most recent uploads for view/download history."""
        from ai.embeddings.chroma_store import ChromaEmbeddingStore

        versions = list(DatabaseVersion.objects.order_by("-version_number"))
        if len(versions) <= DATABASE_UPLOADS_TO_RETAIN:
            return

        stale = versions[DATABASE_UPLOADS_TO_RETAIN:]
        stale_ids = [v.pk for v in stale]
        store = ChromaEmbeddingStore()
        for version_id in stale_ids:
            store.reset_version(version_id)
        deleted_count = DatabaseVersion.objects.filter(pk__in=stale_ids).count()
        DatabaseVersion.objects.filter(pk__in=stale_ids).delete()
        logger.info("Retention: removed %s old database upload(s)", deleted_count)
