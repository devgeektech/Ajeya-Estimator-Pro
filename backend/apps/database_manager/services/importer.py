"""Database import service.

Implements the documented import workflow (docs/AGENTS.md - Database Rules):

Validate -> Backup -> Import -> Activate -> Generate Embeddings

The whole operation runs inside a single transaction so a failure leaves the
previously active database untouched. Embedding generation runs synchronously
after activation and never queues a Celery task.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction

from common.constants import DATABASE_VERSIONS_TO_RETAIN
from common.exceptions import ImportError_
from utils.excel import read_rows
from ai.context import clear_database_context_cache

from ..models import (
    DatabaseVersion,
    LabourMaster,
    LabourStructureSource,
    RateMaster,
    StateControl,
    TORAccessories,
    TORLabour,
    TORMain,
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
        return 0
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
        "state": _to_str(row.get("state")),
        "labour_multiplier": _to_decimal(row.get("labour_multiplier"), "1"),
    }


# Per-sheet field extraction. Each builder receives a normalized row dict and
# returns model field kwargs (excluding the database_version FK).
def _rate_fields(row: dict) -> dict:
    tech_key = _to_str(row.get("tech_key")) or _synth_rate_code(row)
    supplier = _to_str(row.get("supplier"))
    sub_category = _to_str(row.get("sub_category"))
    net_material_rate = _to_decimal(_discounted_rate(row))
    final_amount = _to_decimal(_final_amount(row))
    return {
        "tech_key": tech_key,
        "make": _to_str(row.get("make")),
        "final_amount_excl_gst": final_amount,
        "unit": _to_str(row.get("unit")),
        "category": _to_str(row.get("category")),
        "sub_category": sub_category,
        "product_class": _to_str(row.get("class")),
        "size_mm": _to_optional_decimal(_row_value(row, "size_mm", "size")),
        "capacity": _to_str(row.get("capacity")),
        "height": _to_str(row.get("height")),
        "working_pressure": _to_str(row.get("working_pressure")),
        "test_pressure": _to_str(row.get("test_pressure")),
        "temperature": _to_str(_row_value(row, "temperature", "temp")),
        "throw_distance": _to_str(_row_value(row, "throw_distance", "throw")),
        "k_factor": _to_str(_row_value(row, "k_factor", "kfactor")),
        "head": _to_str(row.get("head")),
        "supplier": supplier,
        "base_purchase_rate": _to_decimal(row.get("base_purchase_rate")),
        "discount_percent": _to_decimal(
            _row_value(row, "discount_percent", "discount")
        ),
        "net_material_rate": net_material_rate,
        "accessories_percent": _to_decimal(
            _row_value(row, "accessories_percent", "accessories")
        ),
        "handling_percent": _to_decimal(
            _row_value(row, "handling_percent", "handling")
        ),
        "wastage_percent": _to_decimal(_row_value(row, "wastage_percent", "wastage")),
        "profit_percent": _to_decimal(_row_value(row, "profit_percent", "profit")),
        "status": _to_str(row.get("status")),
        "procurement_percent": _to_decimal(
            _row_value(row, "procurement_percent", "procurement")
        ),
        "procurement_value": _to_decimal(row.get("procurement_value")),
        "commercial_material_base": _to_decimal(row.get("commercial_material_base")),
        "accessories_value": _to_decimal(row.get("accessories_value")),
        "handling_value": _to_decimal(row.get("handling_value")),
        "wastage_value": _to_decimal(row.get("wastage_value")),
        "subtotal_before_profit": _to_decimal(row.get("subtotal_before_profit")),
        "profit_value": _to_decimal(row.get("profit_value")),
        "final_expenditure": _to_decimal(row.get("final_expenditure")),
        "margin_percent_on_selling": _to_decimal(
            _row_value(row, "margin_percent_on_selling", "margin_on_selling")
        ),
    }


def _labour_fields(row: dict) -> dict:
    tech_key = _to_str(row.get("tech_key")) or _synth_rate_code(row)
    sub_category = _to_str(row.get("sub_category"))

    return {
        "tech_key": tech_key,
        "state": _to_str(row.get("state")),
        "category": _to_str(row.get("category")),
        "sub_category": sub_category,
        "size": _to_str(row.get("size")),
        "unit": _to_str(row.get("unit")),
        "labour_type": _to_str(row.get("labour_type")),
        "base_rate": _to_decimal(row.get("base_rate")),
        "size_factor": _to_decimal(row.get("size_factor")),
        "labour_rate_per_unit": _to_decimal(row.get("labour_rate_per_unit")),
        "testing_percent": _to_decimal(_row_value(row, "testing_percent", "testing")),
        "scaffolding_percent": _to_decimal(
            _row_value(row, "scaffolding_percent", "scaffolding")
        ),
        "consumables_percent": _to_decimal(
            _row_value(row, "consumables_percent", "consumables")
        ),
        "painting_rate": _to_decimal(row.get("painting_rate")),
        "testing_labour_value": _to_decimal(row.get("testing_labour_value")),
        "scaffolding_labour_value": _to_decimal(row.get("scaffolding_labour_value")),
        "consumables_labour_value": _to_decimal(row.get("consumables_labour_value")),
        "painting_labour_value": _to_decimal(row.get("painting_labour_value")),
        "labour_buffer_percent": _to_decimal(
            _row_value(row, "labour_buffer_percent", "labour_buffer")
        ),
        "labour_buffer_value": _to_decimal(row.get("labour_buffer_value")),
        "total_labour_per_unit": _to_decimal(row.get("total_labour_per_unit")),
        "labour_multiplier": _to_decimal(row.get("labour_multiplier"), "1"),
        "total_labour_with_multiplier": _to_decimal(
            _row_value(
                row,
                "total_labour_with_multiplier",
                "total_labour_per_unit_with_labour_multiplier",
            )
        ),
    }


def _tor_main_fields(row: dict) -> dict:
    return {
        "category": _to_str(row.get("category")),
        "handling_percent": _to_decimal(
            _row_value(row, "handling_percent", "handling")
        ),
        "wastage_percent": _to_decimal(_row_value(row, "wastage_percent", "wastage")),
        "profit_percent": _to_decimal(_row_value(row, "profit_percent", "profit")),
        "procurement_percent": _to_decimal(
            _row_value(row, "procurement_percent", "procurement")
        ),
        "risk_buffer_percent": _to_decimal(
            _row_value(row, "risk_buffer_percent", "risk_buffer")
        ),
        "project_state": _to_str(row.get("project_state")),
    }


def _labour_structure_fields(row: dict) -> dict:
    return {
        "category": _to_str(row.get("category")),
        "sub_category": _to_str(row.get("sub_category")),
        "size": _to_str(row.get("size")),
        "unit": _to_str(row.get("unit")),
        "tech_key": _to_str(row.get("tech_key")),
    }


def _tor_labour_fields(row: dict) -> dict:
    return {
        "testing_percent": _to_decimal(_row_value(row, "testing_percent", "testing")),
        "scaffolding_percent": _to_decimal(
            _row_value(row, "scaffolding_percent", "scaffolding")
        ),
        "consumables_percent": _to_decimal(
            _row_value(row, "consumables_percent", "consumables")
        ),
        "painting_rate": _to_decimal(row.get("painting_rate")),
        "labour_buffer_percent": _to_decimal(
            _row_value(row, "labour_buffer_percent", "labour_buffer")
        ),
    }


def _tor_accessories_fields(row: dict) -> dict:
    return {
        "category": _to_str(row.get("category")),
        "sub_category": _to_str(row.get("sub_category")),
        "min_size": _to_optional_decimal(row.get("min_size")),
        "max_size": _to_optional_decimal(row.get("max_size")),
        "accessories_percent": _to_decimal(
            _row_value(row, "accessories_percent", "accessories")
        ),
    }


# Sheet name -> (model, field builder). These are version-scoped tables.
VERSIONED_SHEETS = {
    "Rate_Master": (RateMaster, _rate_fields),
    "Labour_Master": (LabourMaster, _labour_fields),
    "TOR_Main": (TORMain, _tor_main_fields),
    "Labour_Structure_Source": (LabourStructureSource, _labour_structure_fields),
    "TOR_Labour": (TORLabour, _tor_labour_fields),
    "TOR_Accessories": (TORAccessories, _tor_accessories_fields),
    "State_Control_List": (StateControl, _state_control_fields),
}

REQUIRED_MODEL_FIELDS = {
    RateMaster: ("tech_key",),
    LabourMaster: ("tech_key",),
    TORMain: ("category",),
    LabourStructureSource: ("tech_key",),
    TORLabour: (),
    TORAccessories: ("category", "sub_category"),
    StateControl: ("state",),
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
        for sheet_name, (model, builder) in VERSIONED_SHEETS.items():
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
        """Generate embeddings inline for the imported RateMaster rows."""
        from ai.embeddings.generate_database_embeddings import (
            generate_embeddings_for_version,
        )

        summary = generate_embeddings_for_version(version.pk)
        logger.info(
            "Embedding generation finished for v%s: %s", version.version_number, summary
        )

    def _activate(self, version: DatabaseVersion) -> None:
        DatabaseVersion.objects.exclude(pk=version.pk).update(is_active=False)
        version.is_active = True
        version.save(update_fields=["is_active"])

    def _enforce_retention(self) -> None:
        """Keep only the active version and two rollback versions."""
        versions = list(DatabaseVersion.objects.order_by("-version_number"))
        if len(versions) <= DATABASE_VERSIONS_TO_RETAIN:
            return

        stale_ids = [v.pk for v in versions[DATABASE_VERSIONS_TO_RETAIN:]]
        deleted_count = DatabaseVersion.objects.filter(pk__in=stale_ids).count()
        DatabaseVersion.objects.filter(pk__in=stale_ids).delete()
        logger.info("Retention: removed %s old database version(s)", deleted_count)
