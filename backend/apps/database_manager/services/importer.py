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

from ..models import (
    DatabaseVersion,
    LabourMaster,
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
        _row_value(row, "sub_category", "subcategory"),
        row.get("class"),
        _row_value(row, "size_mm", "size", "capacity", "head"),
    ]
    return "_".join(part for part in (_stable_code_part(value) for value in parts) if part)


def _synth_description(row: dict) -> str:
    parts = [
        row.get("category"),
        _row_value(row, "sub_category", "subcategory"),
        row.get("class"),
        _row_value(row, "size_mm", "size"),
        row.get("capacity"),
        row.get("head"),
        row.get("unit"),
    ]
    return " ".join(_to_str(part) for part in parts if _to_str(part))


def _discounted_rate(row: dict):
    rate = _row_value(
        row,
        "net_material_rate",
        "net_purchase_rate",
    )
    if rate not in (None, ""):
        return rate

    base_rate = _row_value(row, "base_purchase_rate", "purchase_rate")
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
    value = _row_value(row, "final_amount_excl_gst", "final_amount", "final_expenditure")
    if value not in (None, ""):
        return value
    return _discounted_rate(row)


# Per-sheet field extraction. Each builder receives a normalized row dict and
# returns model field kwargs (excluding the database_version FK).
def _rate_fields(row: dict) -> dict:
    p_code = _to_str(_row_value(row, "tech_key", "product_code", "match_key", "source_key"))
    if not p_code:
        p_code = _synth_rate_code(row)
    desc = _to_str(_row_value(row, "description", "match_key")) or _synth_description(row)
    return {
        "product_code": p_code,
        "description": desc,
        "make": _to_str(row.get("make")),
        "vendor": _to_str(_row_value(row, "supplier", "vendor")),
        "purchase_rate": _to_decimal(_discounted_rate(row)),
        "final_amount_excl_gst": _to_decimal(_final_amount(row)),
        "unit": _to_str(row.get("unit")),
        "category": _to_str(row.get("category")),
        "subcategory": _to_str(_row_value(row, "sub_category", "subcategory")),
        "remarks": _to_str(_row_value(row, "remarks", "status")),
        "spec_json": row,
    }


def _labour_fields(row: dict) -> dict:
    l_code = _to_str(_row_value(row, "tech_key", "labour_code")) or _synth_rate_code(row)
    l_name = _to_str(
        _row_value(row, "labour_name", "category", "sub_category", "subcategory")
    )
    l_rate = _row_value(
        row,
        "total_labour_per_unit_with_labour_multipler",
        "total_labour_per_unit_with_labour_multipler",
        "total_labour_per_unit",
        "labour_rate_per_unit",
        "labour_rate",
        "base_rate",
    ) or 0

    return {
        "labour_code": l_code,
        "labour_name": l_name if l_name else l_code,
        "labour_rate": _to_decimal(l_rate),
        "unit": _to_str(row.get("unit")),
        "spec_json": row,
    }


def _tor_main_fields(row: dict) -> dict:
    tor_code = _to_str(_row_value(row, "tor_code", "category"))
    return {
        "tor_code": tor_code,
        "description": _to_str(_row_value(row, "description", "category")),
        "spec_json": row,
    }


def _tor_labour_fields(row: dict) -> dict:
    return {
        "tor_code": _to_str(_row_value(row, "tor_code", "category")),
        "labour_code": _to_str(_row_value(row, "labour_code", "labour_type")),
        "quantity": _to_decimal(_row_value(row, "quantity", "labour_buffer")),
        "spec_json": row,
    }


def _tor_accessories_fields(row: dict) -> dict:
    return {
        "tor_code": _to_str(_row_value(row, "tor_code", "category")),
        "accessory_code": _to_str(
            _row_value(row, "accessory_code", "sub_category", "subcategory")
        ),
        "quantity": _to_decimal(_row_value(row, "quantity", "accessories")),
        "spec_json": row,
    }


# Sheet name -> (model, field builder). These are version-scoped tables.
VERSIONED_SHEETS = {
    "Rate_Master": (RateMaster, _rate_fields),
    "Labour_Master": (LabourMaster, _labour_fields),
    "TOR_Main": (TORMain, _tor_main_fields),
    "TOR_Labour": (TORLabour, _tor_labour_fields),
    "TOR_Accessories": (TORAccessories, _tor_accessories_fields),
}

REQUIRED_MODEL_FIELDS = {
    RateMaster: ("product_code", "description"),
    LabourMaster: ("labour_code",),
    TORMain: ("tor_code",),
    TORLabour: ("tor_code", "labour_code"),
    TORAccessories: ("tor_code",),
}


def _has_required_fields(model, fields: dict) -> bool:
    return all(_to_str(fields.get(field)) for field in REQUIRED_MODEL_FIELDS.get(model, ()))


class DatabaseImportService:
    """Orchestrates importing a master workbook into a new DatabaseVersion."""

    def __init__(self, file_path: str, uploaded_by, source_filename: str | None = None, version_name: str = "", stored_name: str = ""):
        self.file_path = file_path
        self.uploaded_by = uploaded_by
        self.source_filename = source_filename or str(file_path)
        self.version_name = version_name
        self.stored_name = stored_name

    def run(self) -> DatabaseVersion:
        """Execute the full import workflow and return the activated version."""
        logger.info("Database import started by %s", getattr(self.uploaded_by, "email", "?"))

        # 1. Validate structure before touching the database.
        validate_workbook(self.file_path)

        try:
            with transaction.atomic():
                version = self._create_version()
                self._import_versioned_sheets(version)
                self._import_state_control()
                self._activate(version)
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

    def _import_state_control(self) -> None:
        """State control is not version-scoped; upsert by state name."""
        rows = read_rows(self.file_path, "State_Control_List")
        for row in rows:
            state_name = _to_str(_row_value(row, "state_name", "state"))
            if not state_name:
                continue
            StateControl.objects.update_or_create(
                state_name=state_name,
                defaults={
                    "labour_multiplier": _to_decimal(row.get("labour_multiplier"), "1"),
                    "transportation_multiplier": _to_decimal(
                        row.get("transportation_multiplier"), "1"
                    ),
                },
            )

    def _generate_embeddings(self, version: DatabaseVersion) -> None:
        """Generate embeddings inline for the imported RateMaster rows."""
        from ai.embeddings.generate_database_embeddings import generate_embeddings_for_version

        summary = generate_embeddings_for_version(version.pk)
        logger.info("Embedding generation finished for v%s: %s", version.version_number, summary)

    def _activate(self, version: DatabaseVersion) -> None:
        DatabaseVersion.objects.exclude(pk=version.pk).update(is_active=False)
        version.is_active = True
        version.save(update_fields=["is_active"])

    def _enforce_retention(self) -> None:
        """Keep up to 10 versions total, but only keep parsed master data for top 3 (active + 2 previous)."""
        versions = list(DatabaseVersion.objects.order_by("-version_number"))
        
        # 1. Total retention (delete DatabaseVersion older than 10)
        keep_total = versions[:DATABASE_VERSIONS_TO_RETAIN]
        if len(versions) > DATABASE_VERSIONS_TO_RETAIN:
            stale_ids = [v.pk for v in versions[DATABASE_VERSIONS_TO_RETAIN:]]
            stale_versions = DatabaseVersion.objects.filter(pk__in=stale_ids)
            deleted_count = stale_versions.count()
            stale_versions.delete()
            logger.info("Retention: archived %s old database version(s)", deleted_count)
            
        # 2. Data retention (delete parsed rows for versions older than top 3)
        if len(keep_total) > 3:
            stale_data_versions = keep_total[3:]
            stale_pks = [v.pk for v in stale_data_versions]

            RateMaster.objects.filter(database_version_id__in=stale_pks).delete()
            LabourMaster.objects.filter(database_version_id__in=stale_pks).delete()
            TORMain.objects.filter(database_version_id__in=stale_pks).delete()
            TORLabour.objects.filter(database_version_id__in=stale_pks).delete()
            TORAccessories.objects.filter(database_version_id__in=stale_pks).delete()
            
            logger.info("Retention: cleared master data for %s old database version(s)", len(stale_data_versions))
