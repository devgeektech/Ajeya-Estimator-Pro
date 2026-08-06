"""Export priced BOQ workbook: original BOQ sheet or client Review sheet."""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.text import slugify
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from apps.boq.models import BOQ
from apps.boq.services.boq_price_calculation_service import (
    build_row_pricing,
    unmatched_qty_row_ids,
)
from apps.boq.services.boq_review_display_service import (
    REVIEW_OUTPUT_HEADER_SPECS,
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
_UNIT_KEYS = ("unit", "uom")
_UNMATCHED_STATUSES = frozenset({"unmatched", "pending", "not_searched", "no_match"})

_DARK_BORDER = Border(
    left=Side(style="thin", color="000000"),
    right=Side(style="thin", color="000000"),
    top=Side(style="thin", color="000000"),
    bottom=Side(style="thin", color="000000"),
)
_CELL_ALIGNMENT = Alignment(horizontal="left", vertical="top", wrap_text=True)
_HEADER_FONT = Font(bold=True)
_RED_HEADER_FONT = Font(bold=True, color="FFFF0000")
_MISSING_PRODUCT_FILL = PatternFill(
    start_color="FFFFC7CE",
    end_color="FFFFC7CE",
    fill_type="solid",
)


def _header_keys(
    headers: list[dict[str, Any]],
) -> tuple[str | None, str | None, str | None, str | None]:
    rate_key = amount_key = qty_key = unit_key = None
    for header in headers:
        key = str(header.get("key") or "").lower()
        if not rate_key and key in _RATE_KEYS:
            rate_key = header["key"]
        if not amount_key and key in _AMOUNT_KEYS:
            amount_key = header["key"]
        if not qty_key and key in _QTY_KEYS:
            qty_key = header["key"]
        if not unit_key and key in _UNIT_KEYS:
            unit_key = header["key"]
    return rate_key, amount_key, qty_key, unit_key


def _header_excel_column(headers: list[dict[str, Any]], key: str | None) -> int | None:
    if not key:
        return None
    for header in headers:
        if header.get("key") != key:
            continue
        try:
            return int(header["index"]) + 1
        except (KeyError, TypeError, ValueError):
            return None
    return None


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


def _product_is_unmatched(product: dict[str, Any]) -> bool:
    status = str(product.get("status") or "").strip().lower()
    line_output = product.get("line_output") or {}
    if status in _UNMATCHED_STATUSES:
        return True
    if line_output.get("is_blank") and status != "matched":
        return True
    if status != "matched":
        return True
    return False


def _highlight_row(sheet: Worksheet, row_number: int, *, max_column: int | None = None) -> None:
    last_col = max_column or sheet.max_column or 1
    for col_idx in range(1, int(last_col) + 1):
        sheet.cell(row=row_number, column=col_idx).fill = _MISSING_PRODUCT_FILL


def _style_cell(cell) -> None:
    cell.alignment = _CELL_ALIGNMENT
    cell.border = _DARK_BORDER


def _style_used_range(
    sheet: Worksheet,
    *,
    skip_blank_rows: bool = True,
    red_header_columns: set[int] | None = None,
) -> None:
    """Apply top/right wrap alignment and dark borders to used cells."""
    if sheet.max_row is None or sheet.max_column is None:
        return
    red_cols = red_header_columns or set()
    for row_idx in range(1, sheet.max_row + 1):
        row_cells = list(sheet[row_idx])
        if skip_blank_rows and all(cell.value in (None, "") for cell in row_cells):
            continue
        for cell in row_cells:
            _style_cell(cell)
        if row_idx == 1:
            for col_idx, cell in enumerate(row_cells, start=1):
                cell.font = _RED_HEADER_FONT if col_idx in red_cols else _HEADER_FONT


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


def _resolve_uploaded_path(uploaded_file) -> str | None:
    if not uploaded_file:
        return None
    try:
        if hasattr(uploaded_file, "path"):
            path = str(uploaded_file.path)
            if path and Path(path).is_file():
                return path
    except Exception:
        pass
    name = getattr(uploaded_file, "name", None)
    if not name:
        return None
    try:
        path = default_storage.path(name)
    except Exception:
        return None
    return path if path and Path(path).is_file() else None


class BOQExportService:
    """Write either the priced original BOQ sheet or the client Review sheet."""

    def __init__(self, boq_id: int, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq_id = boq_id
        self.confirmations = confirmations or {}

    def run(self, kind: str = EXPORT_KIND_REVIEW) -> tuple[bytes, str]:
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

        slug = slugify(boq.boq_name) or "boq"
        # Always rebuild from live Review display so Rate/Amount land on qty rows.
        pricing = build_row_pricing(display)
        highlight_ids = unmatched_qty_row_ids(display, boq_data=boq.boq_data or {})

        if kind == EXPORT_KIND_BOQ:
            payload = self._export_boq_workbook(
                boq,
                boq.boq_data or {},
                pricing,
                highlight_ids,
            )
            filename = f"{slug}-boq.xlsx"
            audit_label = "Exported BOQ sheet"
        else:
            workbook = Workbook()
            sheet = workbook.active
            if sheet is None:
                sheet = workbook.create_sheet(_REVIEW_SHEET_TITLE)
            else:
                sheet.title = _REVIEW_SHEET_TITLE
            self._write_review_sheet(sheet, display)
            buffer = BytesIO()
            workbook.save(buffer)
            payload = buffer.getvalue()
            filename = f"{slug}-review.xlsx"
            audit_label = "Exported Review sheet"

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
        return payload, filename

    def _export_boq_workbook(
        self,
        boq: BOQ,
        boq_data: dict[str, Any],
        pricing: dict[str, dict[str, Any]],
        highlight_ids: set[str],
    ) -> bytes:
        """Prefer the original upload layout; fall back to a rebuilt sheet."""
        path = _resolve_uploaded_path(boq.uploaded_file)
        if path:
            try:
                return self._fill_original_boq_workbook(
                    path,
                    boq_data,
                    pricing,
                    highlight_ids,
                )
            except Exception:
                logger.exception(
                    "Original BOQ fill failed for id=%s; rebuilding from JSON",
                    boq.pk,
                )

        workbook = Workbook()
        sheet = workbook.active
        if sheet is None:
            sheet = workbook.create_sheet(_BOQ_SHEET_TITLE)
        else:
            sheet.title = _BOQ_SHEET_TITLE
        self._write_boq_sheet(sheet, boq_data, pricing, highlight_ids)
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def _fill_original_boq_workbook(
        self,
        path: str,
        boq_data: dict[str, Any],
        pricing: dict[str, dict[str, Any]],
        highlight_ids: set[str],
    ) -> bytes:
        """Copy the uploaded workbook and write Rate/Amount only on qty+unit rows."""
        workbook = load_workbook(path)
        headers = list(boq_data.get("headers") or [])
        rate_key, amount_key, qty_key, unit_key = _header_keys(headers)
        rate_col = _header_excel_column(headers, rate_key)
        amount_col = _header_excel_column(headers, amount_key)
        if rate_col is None and amount_col is None:
            raise ValueError("Uploaded BOQ has no Rate or Amount column to fill.")

        sheets_by_name = {name: workbook[name] for name in workbook.sheetnames}
        default_sheet = workbook.active
        used_columns = max((int(h.get("index") or 0) + 1 for h in headers), default=1)

        for row in boq_data.get("rows") or []:
            row_id = str(row.get("row_id") or "")
            excel_row = row.get("excel_row_number")
            try:
                excel_row_number = int(excel_row)
            except (TypeError, ValueError):
                continue
            if excel_row_number < 1:
                continue

            sheet_name = str(row.get("sheet_name") or "").strip()
            sheet = sheets_by_name.get(sheet_name) if sheet_name else None
            if sheet is None:
                sheet = default_sheet
            if sheet is None:
                continue

            qty_value = cell_value(row, qty_key) if qty_key else None
            unit_value = cell_value(row, unit_key) if unit_key else None
            has_qty = _is_filled(qty_value)
            has_unit = (not unit_key) or _is_filled(unit_value)
            can_price = has_qty and has_unit

            if can_price:
                priced = pricing.get(row_id)
                if priced:
                    if rate_col is not None and priced.get("rate") not in (None, ""):
                        sheet.cell(
                            row=excel_row_number,
                            column=rate_col,
                            value=priced.get("rate"),
                        )
                    if amount_col is not None and priced.get("amount") not in (None, ""):
                        sheet.cell(
                            row=excel_row_number,
                            column=amount_col,
                            value=priced.get("amount"),
                        )

            if row_id in highlight_ids and can_price:
                _highlight_row(sheet, excel_row_number, max_column=used_columns)

        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def _write_boq_sheet(
        sheet: Worksheet,
        boq_data: dict[str, Any],
        pricing: dict[str, dict[str, Any]],
        highlight_ids: set[str],
    ) -> None:
        """Fallback rebuild when the original workbook cannot be loaded."""
        headers = boq_data.get("headers") or []
        rate_key, amount_key, qty_key, unit_key = _header_keys(headers)
        sheet.append([header.get("label") or header.get("key") or "" for header in headers])
        highlight_sheet_rows: list[int] = []

        for row in boq_data.get("rows") or []:
            row_id = str(row.get("row_id") or "")
            row_values: dict[str, Any] = {}
            for header in headers:
                key = header.get("key")
                if not key:
                    continue
                row_values[key] = cell_value(row, key)

            qty_value = row_values.get(qty_key) if qty_key else None
            unit_value = row_values.get(unit_key) if unit_key else None
            can_price = _is_filled(qty_value) and (
                not unit_key or _is_filled(unit_value)
            )
            priced = pricing.get(row_id) if can_price else None
            if priced:
                if rate_key:
                    row_values[rate_key] = priced.get("rate")
                if amount_key:
                    row_values[amount_key] = priced.get("amount")

            sheet.append([row_values.get(header.get("key")) for header in headers])
            if can_price and row_id in highlight_ids:
                highlight_sheet_rows.append(sheet.max_row)

        for row_number in highlight_sheet_rows:
            _highlight_row(sheet, row_number, max_column=len(headers) or 1)

        _style_used_range(sheet, skip_blank_rows=True)
        _autosize_columns(sheet)

    @staticmethod
    def _write_review_sheet(sheet: Worksheet, display: dict[str, Any]) -> None:
        sheet.append(list(REVIEW_OUTPUT_HEADERS))
        col_count = len(REVIEW_OUTPUT_HEADERS)
        red_header_columns = {
            index
            for index, (_label, is_red) in enumerate(REVIEW_OUTPUT_HEADER_SPECS, start=1)
            if is_red
        }
        lines = list(display.get("lines") or [])
        highlight_sheet_rows: list[int] = []

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
                    if _product_is_unmatched(product):
                        highlight_sheet_rows.append(sheet.max_row)

            next_line = lines[index + 1] if index + 1 < len(lines) else None
            if next_line is not None and _row_depth(next_line) == 0:
                sheet.append([None] * col_count)

        for row_number in highlight_sheet_rows:
            _highlight_row(sheet, row_number, max_column=col_count)

        _style_used_range(
            sheet,
            skip_blank_rows=True,
            red_header_columns=red_header_columns,
        )
        _autosize_columns(sheet, max_width=36)
