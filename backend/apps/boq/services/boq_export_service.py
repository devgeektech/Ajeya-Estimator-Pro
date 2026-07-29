"""Export confirmed BOQ analysis to a two-sheet Excel workbook."""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils.text import slugify
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from apps.boq.models import BOQ
from apps.boq.services.boq_price_calculation_service import build_row_pricing
from apps.boq.services.boq_review_display_service import BOQReviewDisplayService
from apps.boq.services.serial_normalizer import cell_value
from common.choices import BOQStatus

logger = logging.getLogger("boq_ai")

_BOQ_SHEET_TITLE = "BOQ"
_BREAKDOWN_SHEET_TITLE = "Charge Breakdown"

_RATE_KEYS = ("rate", "unit_rate", "price")
_AMOUNT_KEYS = ("amount", "total", "total_amount", "amt")
_QTY_KEYS = ("qty", "quantity", "qnty", "nos")

_DARK_BORDER = Border(
    left=Side(style="thin", color="000000"),
    right=Side(style="thin", color="000000"),
    top=Side(style="thin", color="000000"),
    bottom=Side(style="thin", color="000000"),
)
_CELL_ALIGNMENT = Alignment(horizontal="left", vertical="top", wrap_text=True)
_HEADER_FONT = Font(bold=True)

_BREAKDOWN_HEADERS = [
    "S.No",
    "Description",
    "Qty",
    "Unit",
    "Status",
    "Confirmed",
    "Confidence",
    "Category",
    "Sub Category",
    "Make",
    "Supplier",
    "Tech Key",
    "Material Rate",
    "Labour Rate",
    "Testing Labour",
    "Scaffolding Labour",
    "Consumables Labour",
    "Painting Labour",
    "Labour Buffer",
    "Total Labour / Unit",
    "Material Amount",
    "Labour Amount",
    "Total Amount",
]


def _header_keys(headers: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    rate_key = amount_key = qty_key = None
    for header in headers:
        key = str(header.get("key") or "").lower()
        if not rate_key and key in _RATE_KEYS:
            rate_key = header["key"]
        if not amount_key and key in _AMOUNT_KEYS:
            amount_key = header["key"]
        if not qty_key and key in _QTY_KEYS:
            qty_key = header["key"]
    return rate_key, amount_key, qty_key


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _row_depth(row: dict[str, Any]) -> int:
    try:
        return int(row.get("depth") or 0)
    except (TypeError, ValueError):
        return 0


def _style_cell(cell) -> None:
    cell.alignment = _CELL_ALIGNMENT
    cell.border = _DARK_BORDER


def _style_used_range(sheet: Worksheet, *, skip_blank_rows: bool = True) -> None:
    """Apply top/right wrap alignment and dark borders to used cells."""
    if sheet.max_row is None or sheet.max_column is None:
        return
    for row_idx in range(1, sheet.max_row + 1):
        row_cells = list(sheet[row_idx])
        if skip_blank_rows and all(cell.value in (None, "") for cell in row_cells):
            continue
        for cell in row_cells:
            _style_cell(cell)
        if row_idx == 1:
            for cell in row_cells:
                cell.font = _HEADER_FONT


def _autosize_columns(sheet: Worksheet, *, min_width: int = 10, max_width: int = 42) -> None:
    if sheet.max_column is None:
        return
    for col_idx in range(1, sheet.max_column + 1):
        letter = get_column_letter(col_idx)
        longest = 0
        for cell in sheet[letter]:
            if cell.value is None:
                continue
            longest = max(longest, min(max_width, len(str(cell.value))))
        sheet.column_dimensions[letter].width = max(min_width, longest + 2)


class BOQExportService:
    """Write priced BOQ workbook with original sheet + charge breakdown."""

    def __init__(self, boq_id: int, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq_id = boq_id
        self.confirmations = confirmations or {}

    def run(self) -> tuple[bytes, str]:
        from io import BytesIO

        boq = BOQ.objects.get(pk=self.boq_id)
        analysis = boq.analysis_data or {}
        if boq.status not in {BOQStatus.READY_EXPORT, BOQStatus.EXPORTED} and not analysis.get(
            "pricing_ready"
        ):
            raise ValueError("Finish Labour (Next to Review) before exporting.")

        display = BOQReviewDisplayService(boq, self.confirmations).build()
        if not display.get("has_analysis"):
            raise ValueError("Complete Make & Vendor and Labour before exporting.")

        boq_data = boq.boq_data or {}
        stored_pricing = analysis.get("row_pricing") or {}
        pricing = stored_pricing if isinstance(stored_pricing, dict) and stored_pricing else build_row_pricing(display)

        workbook = Workbook()
        boq_sheet = workbook.active
        if boq_sheet is None:
            boq_sheet = workbook.create_sheet(_BOQ_SHEET_TITLE)
        else:
            boq_sheet.title = _BOQ_SHEET_TITLE
        self._write_boq_sheet(boq_sheet, boq_data, pricing)

        breakdown_sheet = workbook.create_sheet(_BREAKDOWN_SHEET_TITLE)
        self._write_breakdown_sheet(breakdown_sheet, display)

        buffer = BytesIO()
        workbook.save(buffer)
        filename = f"{slugify(boq.boq_name) or 'boq'}-export.xlsx"

        with transaction.atomic():
            if boq.status != BOQStatus.EXPORTED:
                boq.status = BOQStatus.EXPORTED
                boq.save(update_fields=["status"])

        logger.info("Exported BOQ workbook for id=%s (%s)", boq.pk, filename)
        from apps.audit.services import record
        from apps.notifications.services import notify

        record(getattr(boq, "user", None), "Exported BOQ", "BOQ", boq.boq_name)
        notify(
            getattr(boq, "user", None),
            "BOQ exported",
            f"BOQ '{boq.boq_name}' was exported as {filename}.",
        )
        return buffer.getvalue(), filename

    @staticmethod
    def _write_boq_sheet(
        sheet: Worksheet,
        boq_data: dict[str, Any],
        pricing: dict[str, dict[str, Any]],
    ) -> None:
        headers = boq_data.get("headers") or []
        rate_key, amount_key, qty_key = _header_keys(headers)
        col_count = max(len(headers), 1)
        sheet.append([header.get("label") or header.get("key") or "" for header in headers])

        rows = list(boq_data.get("rows") or [])
        for index, row in enumerate(rows):
            row_id = str(row.get("row_id") or "")
            row_values: dict[str, Any] = {}
            for header in headers:
                key = header.get("key")
                if not key:
                    continue
                row_values[key] = cell_value(row, key)

            # Only fill Rate / Amount on item rows that already have Quantity.
            qty_value = row_values.get(qty_key) if qty_key else None
            priced = pricing.get(row_id) if _is_filled(qty_value) else None
            if priced:
                if rate_key:
                    row_values[rate_key] = priced.get("rate")
                if amount_key:
                    row_values[amount_key] = priced.get("amount")

            sheet.append([row_values.get(header.get("key")) for header in headers])

            # Blank separator after each section (before the next depth-0 row).
            next_row = rows[index + 1] if index + 1 < len(rows) else None
            if next_row is not None and _row_depth(next_row) == 0:
                sheet.append([None] * col_count)

        _style_used_range(sheet, skip_blank_rows=True)
        _autosize_columns(sheet)

    @staticmethod
    def _write_breakdown_sheet(sheet: Worksheet, display: dict[str, Any]) -> None:
        sheet.append(_BREAKDOWN_HEADERS)
        col_count = len(_BREAKDOWN_HEADERS)
        lines = list(display.get("lines") or [])

        for index, line in enumerate(lines):
            products = line.get("products") or []
            if not products:
                sheet.append(
                    [
                        line.get("serial"),
                        line.get("description"),
                        line.get("qty"),
                        line.get("unit"),
                        line.get("status"),
                    ]
                    + [None] * (col_count - 5)
                )
            else:
                for product in products:
                    selected = product.get("selected") or {}
                    line_output = product.get("line_output") or {}
                    labour_components = line_output.get("labour_components") or {}
                    sheet.append(
                        [
                            line.get("serial"),
                            line.get("description"),
                            line.get("qty"),
                            line.get("unit"),
                            product.get("status"),
                            "Yes" if product.get("is_confirmed") else "No",
                            product.get("confidence"),
                            selected.get("category") or product.get("extracted_category"),
                            selected.get("sub_category")
                            or product.get("extracted_sub_category"),
                            selected.get("make"),
                            selected.get("supplier"),
                            selected.get("tech_key"),
                            line_output.get("material_rate"),
                            line_output.get("labour_rate"),
                            labour_components.get("testing_labour_value"),
                            labour_components.get("scaffolding_labour_value"),
                            labour_components.get("consumables_labour_value"),
                            labour_components.get("painting_labour_value"),
                            labour_components.get("labour_buffer_value"),
                            labour_components.get("total_labour_per_unit_with_multiplier")
                            or labour_components.get("total_labour_per_unit"),
                            line_output.get("material_amount"),
                            line_output.get("labour_amount"),
                            line_output.get("total_amount"),
                        ]
                    )

            # Empty row after each BOQ line / section group.
            next_line = lines[index + 1] if index + 1 < len(lines) else None
            if next_line is not None and _row_depth(next_line) == 0:
                sheet.append([None] * col_count)
            elif next_line is None:
                pass
            elif _row_depth(line) == 0 and _row_depth(next_line) == 0:
                sheet.append([None] * col_count)

        _style_used_range(sheet, skip_blank_rows=True)
        _autosize_columns(sheet)
