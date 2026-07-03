"""Database import service.

Implements the documented import workflow (docs/AGENTS.md - Database Rules):

    Validate -> Backup -> Import -> Generate Embeddings -> Activate

The whole operation runs inside a single transaction so a failure leaves the
previously active database untouched. Embedding generation is delegated to the
AI layer and is deferred until the AI/matching sprints; the hook is invoked
here so the workflow order is preserved.
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


# Per-sheet field extraction. Each builder receives a normalized row dict and
# returns model field kwargs (excluding the database_version FK).
def _rate_fields(row: dict) -> dict:
    # 1. Product code: Excel has "tech_key"
    p_code = _to_str(row.get("tech_key") or row.get("product_code"))
    
    # 2. Description: if not present, synthesize from category, subcategory, class, size
    desc = _to_str(row.get("description"))
    if not desc:
        parts = [
            _to_str(row.get("category")),
            _to_str(row.get("sub_category") or row.get("subcategory")),
            _to_str(row.get("class")),
            _to_str(row.get("size_mm") or row.get("size")),
        ]
        desc = " ".join([p for p in parts if p])
    
    # 3. Purchase rate: prioritize net rate, then base purchase rate, then purchase rate
    p_rate = row.get("net_material_rate") or row.get("net_purchase_rate") or row.get("base_purchase_rate") or row.get("purchase_rate") or 0

    return {
        "product_code": p_code,
        "description": desc,
        "make": _to_str(row.get("make")),
        "vendor": _to_str(row.get("supplier") or row.get("vendor")),
        "purchase_rate": _to_decimal(p_rate),
        "unit": _to_str(row.get("unit")),
        "category": _to_str(row.get("category")),
        "subcategory": _to_str(row.get("sub_category") or row.get("subcategory")),
        "remarks": _to_str(row.get("remarks") or row.get("status")),
        "spec_json": row,
    }


def _labour_fields(row: dict) -> dict:
    l_code = _to_str(row.get("tech_key") or row.get("labour_code"))
    l_name = _to_str(row.get("category") or row.get("labour_name") or row.get("sub_category") or row.get("subcategory"))
    # Prioritize multi-factor rate, then per-unit, then base rate
    l_rate = row.get("total_labour_per_unit_with__labour__multipler") or row.get("total_labour_per_unit") or row.get("labour_rate_per_unit") or row.get("labour_rate") or row.get("base_rate") or 0

    return {
        "labour_code": l_code,
        "labour_name": l_name if l_name else l_code,
        "labour_rate": _to_decimal(l_rate),
        "unit": _to_str(row.get("unit")),
        "spec_json": row,
    }


def _tor_main_fields(row: dict) -> dict:
    return {
        "tor_code": _to_str(row.get("tor_code")),
        "description": _to_str(row.get("description")),
    }


def _tor_labour_fields(row: dict) -> dict:
    return {
        "tor_code": _to_str(row.get("tor_code")),
        "labour_code": _to_str(row.get("labour_code")),
        "quantity": _to_decimal(row.get("quantity")),
    }


def _tor_accessories_fields(row: dict) -> dict:
    return {
        "tor_code": _to_str(row.get("tor_code")),
        "accessory_code": _to_str(row.get("accessory_code")),
        "quantity": _to_decimal(row.get("quantity")),
    }


# Sheet name -> (model, field builder). These are version-scoped tables.
VERSIONED_SHEETS = {
    "Rate_Master": (RateMaster, _rate_fields),
    "Labour_Master": (LabourMaster, _labour_fields),
    "TOR_Main": (TORMain, _tor_main_fields),
    "TOR_Labour": (TORLabour, _tor_labour_fields),
    "TOR_Accessories": (TORAccessories, _tor_accessories_fields),
}


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
                self._generate_embeddings(version)
                self._activate(version)
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
            objects = [
                model(database_version=version, **builder(row))
                for row in rows
            ]
            if objects:
                model.objects.bulk_create(objects, batch_size=500)
            logger.info("Imported %s rows from %s", len(objects), sheet_name)

    def _import_state_control(self) -> None:
        """State control is not version-scoped; upsert by state name."""
        rows = read_rows(self.file_path, "State_Control_List")
        for row in rows:
            state_name = _to_str(row.get("state_name"))
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
        """Embedding generation hook.

        Real generation is implemented in the AI/matching sprints
        (docs/DATABASE_ARCHITECTURE.md - Embedding Strategy). Kept in the
        workflow so ordering is preserved.
        """
        logger.info("Embedding generation deferred to AI sprint for v%s", version.version_number)

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
