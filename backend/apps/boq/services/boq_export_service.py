"""Export priced BOQ workbook: original BOQ sheet or client Review sheet."""
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
from apps.boq.services.boq_review_display_service import (
    REVIEW_OUTPUT_HEADERS,
    BOQReviewDisplayService,
    review_output_values,
)
from apps.boq.services.serial_normalizer import cell_value
from common.choices import BOQStatus

logger = logging.getLogger("boq_ai")

EXPORT_KIND_BOQ = "boq"
EXPORT_KIND_REVIEW = "review"
_EXPORT_KINDS = {EXPORT_KIND_BOQ, EXPORT_KIND_REVIEW}

_BOQ_SHEET_TITLE = "BOQ"
_REVIEW_SHEET_TITLE = "Review"

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
    """Write either the priced original BOQ sheet or the client Review sheet."""

    def __init__(self, boq_id: int, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq_id = boq_id
        self.confirmations = confirmations or {}

    def run(self, kind: str = EXPORT_KIND_REVIEW) -> tuple[bytes, str]:
        from io import BytesIO

        kind = str(kind or EXPORT_KIND_REVIEW).strip().lower()
        if kind not in _EXPORT_KINDS:
            raise ValueError("Export kind must be 'review' or 'boq'.")

        boq = BOQ.objects.get(pk=self.boq_id)
        analysis = boq.analysis_data or {}
        if boq.status not in {BOQStatus.READY_EXPORT, BOQStatus.EXPORTED} and not analysis.get(
            "pricing_ready"
        ):
            raise ValueError("Finish Labour (Next to Review) before exporting.")

        display = BOQReviewDisplayService(boq, self.confirmations).build()
        if not display.get("has_analysis"):
            raise ValueError("Complete Make & Vendor and Labour before exporting.")

        workbook = Workbook()
        sheet = workbook.active
        slug = slugify(boq.boq_name) or "boq"

        if kind == EXPORT_KIND_BOQ:
            if sheet is None:
                sheet = workbook.create_sheet(_BOQ_SHEET_TITLE)
            else:
                sheet.title = _BOQ_SHEET_TITLE
            boq_data = boq.boq_data or {}
            stored_pricing = analysis.get("row_pricing") or {}
            pricing = (
                stored_pricing
                if isinstance(stored_pricing, dict) and stored_pricing
                else build_row_pricing(display)
            )
            self._write_boq_sheet(sheet, boq_data, pricing)
            filename = f"{slug}-boq.xlsx"
            audit_label = "Exported BOQ sheet"
        else:
            if sheet is None:
                sheet = workbook.create_sheet(_REVIEW_SHEET_TITLE)
            else:
                sheet.title = _REVIEW_SHEET_TITLE
            self._write_review_sheet(sheet, display)
            filename = f"{slug}-review.xlsx"
            audit_label = "Exported Review sheet"

        buffer = BytesIO()
        workbook.save(buffer)

        with transaction.atomic():
            if boq.status != BOQStatus.EXPORTED:
                boq.status = BOQStatus.EXPORTED
                boq.save(update_fields=["status"])

        logger.info("Exported BOQ id=%s kind=%s (%s)", boq.pk, kind, filename)
        from apps.audit.services import record
        from apps.notifications.services import notify

        record(getattr(boq, "user", None), audit_label, "BOQ", boq.boq_name)
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
    def _write_review_sheet(sheet: Worksheet, display: dict[str, Any]) -> None:
        sheet.append(list(REVIEW_OUTPUT_HEADERS))
        col_count = len(REVIEW_OUTPUT_HEADERS)
        lines = list(display.get("lines") or [])

        for index, line in enumerate(lines):
            products = line.get("products") or []
            if not products:
                # Section / empty lines: serial + description + qty only.
                empty = [None] * col_count
                empty[0] = line.get("serial")
                empty[1] = line.get("description")
                empty[18] = line.get("qty")
                sheet.append(empty)
            else:
                for product in products:
                    review_row = product.get("review_output") or {}
                    sheet.append(review_output_values(review_row))

            next_line = lines[index + 1] if index + 1 < len(lines) else None
            if next_line is not None and _row_depth(next_line) == 0:
                sheet.append([None] * col_count)

        _style_used_range(sheet, skip_blank_rows=True)
        _autosize_columns(sheet, max_width=36)
