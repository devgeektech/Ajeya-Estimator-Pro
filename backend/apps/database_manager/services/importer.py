"""Database import service.

Validate -> Backup -> Import -> Activate -> Generate Embeddings

Only ``Product_Helper``, ``Rate_Master_Output``, and ``Labour_Master_Output``
are ingested. Other workbook sheets may exist and are counted for the database
detail UI only. Older workbooks that still use ``Labour_master_Output`` are
accepted via alias; ``Product_Master`` is accepted as ``Product_Helper``.

Product_Helper rows with Status ``Discontinued`` (sheet column I) are not
loaded. Matching Rate_Master_Output / Labour rows for those Product_IDs are
also skipped so they never receive embeddings or appear in Analysis matching.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from common.db import atomic
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from common.constants import MASTER_SHEET_ALIASES, REQUIRED_MASTER_SHEETS
from common.exceptions import ImportError_
from utils.excel import list_sheet_names, read_rows

from .activation import (
    activate_database_version,
    enforce_version_retention,
    purge_inactive_master_data,
)
from ..models import (
    DatabaseVersion,
    Labour_master_Output,
    Product_Helper,
    Rate_Master_Output,
)
from .validator import resolve_master_sheet_name, validate_workbook

logger = logging.getLogger("boq_ai")


def _to_optional_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text or text in {"<<", ">>"} or "missing" in text.lower():
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _to_optional_id(value) -> str | None:
    """
    Normalize a workbook identifier to text.

    IDs may be codes (``P1001``) or numbers. Excel hands whole numbers back as
    floats, so ``1001.0`` is trimmed to ``1001`` to keep rate/labour rows linked.
    """
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    return str(number.to_integral_value()) if number == number.to_integral_value() else text


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


def _to_optional_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
    text = str(value).strip()
    if not text:
        return None
    parsed = parse_datetime(text.replace(" ", "T", 1))
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _is_discontinued_status(value) -> bool:
    """True when Product_Helper Status means the product must not be imported."""
    text = str(value or "").strip().casefold()
    if not text:
        return False
    # Column I on Product_Helper — skip Discontinued (and common synonyms).
    return text in {
        "discontinued",
        "discontinue",
        "inactive",
        "obsolete",
        "withdrawn",
    }


def _product_helper_fields(row: dict) -> dict:
    return {
        "Product_ID": _to_optional_id(row.get("product_id")),
        "Category": _to_optional_str(row.get("category")),
        "Sub_Category": _to_optional_str(row.get("sub_category")),
        "Class": _to_optional_str(row.get("class")),
        "Size": _to_optional_decimal(_row_value(row, "size")),
        "Unit": _to_optional_str(row.get("unit")),
        "Capacity": _to_optional_str(row.get("capacity")),
        "Attribute": _to_optional_str(_row_value(row, "attribute", "attributes")),
        "Status": _to_optional_str(row.get("status")),
    }


def _rate_fields(row: dict) -> dict:
    return {
        "Rate_ID": _to_optional_id(row.get("rate_id")),
        "Product_ID": _to_optional_id(row.get("product_id")),
        "Category": _to_optional_str(row.get("category")),
        "Sub_Category": _to_optional_str(row.get("sub_category")),
        "Class": _to_optional_str(row.get("class")),
        "Size": _to_optional_decimal(_row_value(row, "size")),
        "Unit": _to_optional_str(row.get("unit")),
        "Capacity": _to_optional_str(row.get("capacity")),
        "Attribute": _to_optional_str(_row_value(row, "attribute", "attributes")),
        "Make": _to_optional_str(row.get("make")),
        "Vendor": _to_optional_str(row.get("vendor")),
        "Base_Purchase_Rate": _to_optional_decimal(row.get("base_purchase_rate")),
        "Last_Updated": _to_optional_datetime(row.get("last_updated")),
        "Discount": _to_optional_decimal(row.get("discount")),
        "Net_Material_Rate": _to_optional_decimal(row.get("net_material_rate")),
        "Procurement_Value": _to_optional_decimal(row.get("procurement_value")),
        "Commercial_Material_Base": _to_optional_decimal(
            row.get("commercial_material_base")
        ),
        "Accessories_Value": _to_optional_decimal(row.get("accessories_value")),
        "Handling_Value": _to_optional_decimal(row.get("handling_value")),
        "Wastage_Value": _to_optional_decimal(row.get("wastage_value")),
        "Sub_Total": _to_optional_decimal(
            _row_value(row, "sub_total", "subtotal")
        ),
        "Profit_Value": _to_optional_decimal(row.get("profit_value")),
        "Final_Material_Amount": _to_optional_decimal(
            _row_value(row, "final_material_amount")
        ),
        "Margin_pct_on_Selling": _to_optional_decimal(
            _row_value(
                row,
                "margin_on_selling",
                "margin_pct_on_selling",
                "margin_percent_on_selling",
            )
        ),
    }


def _labour_fields(row: dict) -> dict:
    return {
        "Product_ID": _to_optional_id(row.get("product_id")),
        "Category": _to_optional_str(row.get("category")),
        "Sub_Category": _to_optional_str(row.get("sub_category")),
        "Class": _to_optional_str(row.get("class")),
        "Size": _to_optional_decimal(row.get("size")),
        "Unit": _to_optional_str(row.get("unit")),
        "Capacity": _to_optional_str(row.get("capacity")),
        "Attribute": _to_optional_str(_row_value(row, "attribute", "attributes")),
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
        # Current workbook: Labour_With_State_Multiplier. Older: *_with_labour_Multipler.
        "Total_Labour_per_unit_with_labour_Multipler": _to_optional_decimal(
            _row_value(
                row,
                "labour_with_state_multiplier",
                "total_labour_per_unit_with_labour_multipler",
                "total_labour_with_multiplier",
                "total_labour_per_unit_with_labour_multiplier",
            )
        ),
    }


# Preferred workbook sheet name → (model, row builder). Actual sheet title may
# differ by alias (see MASTER_SHEET_ALIASES / resolve_master_sheet_name).
VERSIONED_SHEETS = {
    "Product_Helper": (Product_Helper, _product_helper_fields),
    "Rate_Master_Output": (Rate_Master_Output, _rate_fields),
    "Labour_Master_Output": (Labour_master_Output, _labour_fields),
}

REQUIRED_MODEL_FIELDS = {
    Product_Helper: ("Product_ID", "Category"),
    Rate_Master_Output: ("Product_ID", "Category"),
    Labour_master_Output: ("Product_ID",),
}


def _has_required_fields(model, fields: dict) -> bool:
    for field in REQUIRED_MODEL_FIELDS.get(model, ()):
        value = fields.get(field)
        if value is None or value == "":
            return False
        if isinstance(value, str) and not value.strip():
            return False
    return True


def _missing_required_fields(model, fields: dict) -> list[str]:
    """Return required field names a built row failed to provide."""
    missing = []
    for field in REQUIRED_MODEL_FIELDS.get(model, ()):
        value = fields.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def _skip_reason(model, sheet_name: str, built_rows: list[dict]) -> str:
    """Explain why every row of a required sheet was rejected."""
    counts: dict[str, int] = {}
    for fields in built_rows:
        for field in _missing_required_fields(model, fields):
            counts[field] = counts.get(field, 0) + 1
    if not counts:
        return f"Sheet '{sheet_name}' has no usable rows."
    columns = ", ".join(sorted(counts))
    return (
        f"Sheet '{sheet_name}' has no usable rows: required column(s) "
        f"{columns} are empty for every row. Check the header spelling and that "
        "the data starts directly under the header row."
    )


def _ingested_sheet_titles() -> set[str]:
    titles: set[str] = set()
    for preferred in REQUIRED_MASTER_SHEETS:
        titles.update(MASTER_SHEET_ALIASES.get(preferred, (preferred,)))
    return titles


def count_workbook_sheet_rows(file_path: str) -> list[dict]:
    """Return [{name, rows, ingested}] for every sheet (UI statistics)."""
    ingested = _ingested_sheet_titles()
    ingested_lower = {name.lower() for name in ingested}
    stats: list[dict] = []
    for sheet_name in list_sheet_names(file_path):
        try:
            rows = read_rows(file_path, sheet_name)
            row_count = len(rows)
        except Exception:  # noqa: BLE001
            logger.exception("Failed counting rows for sheet %s", sheet_name)
            row_count = 0
        stats.append(
            {
                "name": sheet_name,
                "rows": row_count,
                "ingested": sheet_name in ingested or sheet_name.lower() in ingested_lower,
            }
        )
    return stats


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

        validate_workbook(self.file_path)

        try:
            with atomic():
                version = self._create_version()
                self._import_versioned_sheets(version)
                self._activate(version)
            self._generate_embeddings(version)
            purge_inactive_master_data(version)
            enforce_version_retention()
        except ImportError_:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Database import failed")
            message = str(exc)
            if "does not exist" in message and (
                "Rate_Master_Output" in message or "Labour_master_Output" in message
            ):
                raise ImportError_(
                    "Master database tables are missing. Run "
                    "`python manage.py migrate` then upload again."
                ) from exc
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
        available_sheets = list_sheet_names(self.file_path)
        # Product_IDs marked Discontinued on Product_Helper (Status column).
        # Rate / Labour rows for these IDs are also skipped so they are never
        # embedded or returned during Analysis matching.
        discontinued_product_ids: set[str] = set()

        for preferred_name, (model, builder) in VERSIONED_SHEETS.items():
            sheet_name = resolve_master_sheet_name(available_sheets, preferred_name)
            if sheet_name is None:
                raise ImportError_(
                    f"Required sheet '{preferred_name}' is missing from the workbook."
                )
            rows = read_rows(self.file_path, sheet_name)
            objects = []
            rejected: list[dict] = []
            discontinued_skipped = 0
            for row in rows:
                fields = builder(row)
                product_id = str(fields.get("Product_ID") or "").strip()

                if model is Product_Helper and _is_discontinued_status(
                    fields.get("Status")
                ):
                    if product_id:
                        discontinued_product_ids.add(product_id)
                    discontinued_skipped += 1
                    continue

                if (
                    model in {Rate_Master_Output, Labour_master_Output}
                    and product_id
                    and product_id in discontinued_product_ids
                ):
                    discontinued_skipped += 1
                    continue

                if not _has_required_fields(model, fields):
                    rejected.append(fields)
                    continue
                objects.append(model(database_version=version, **fields))
            # A required sheet with data but no importable row is a failed import,
            # not an empty database: fail loudly instead of activating nothing.
            if rows and not objects:
                raise ImportError_(_skip_reason(model, sheet_name, rejected))
            if objects:
                model.objects.bulk_create(objects, batch_size=500)
            logger.info(
                "Imported %s rows from %s (%s missing required fields, "
                "%s discontinued skipped)",
                len(objects),
                sheet_name,
                len(rejected),
                discontinued_skipped,
            )
        if discontinued_product_ids:
            logger.info(
                "Excluded %s discontinued Product_ID(s) from import/embeddings",
                len(discontinued_product_ids),
            )

    def _generate_embeddings(self, version: DatabaseVersion) -> None:
        from ai.embeddings.generator import generate_embeddings_for_version

        summary = generate_embeddings_for_version(version.pk)
        logger.info(
            "Embedding generation finished for v%s: %s", version.version_number, summary
        )

    def _activate(self, version: DatabaseVersion) -> None:
        activate_database_version(version)
