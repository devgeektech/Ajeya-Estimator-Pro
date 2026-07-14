"""Export confirmed BOQ analysis to a two-sheet Excel workbook."""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from django.utils.text import slugify
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_display_service import BOQAnalysisDisplayService
from apps.boq.services.serial_normalizer import cell_value

logger = logging.getLogger("boq_ai")

_BOQ_SHEET_TITLE = "BOQ"
_BREAKDOWN_SHEET_TITLE = "Charge Breakdown"

_RATE_KEYS = ("rate", "unit_rate", "price")
_AMOUNT_KEYS = ("amount", "total", "total_amount", "amt")

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


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _format_decimal(value: Decimal | None) -> Any:
    if value is None:
        return None
    return float(value)


def _header_keys(headers: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    rate_key = amount_key = None
    for header in headers:
        key = str(header.get("key") or "").lower()
        if not rate_key and key in _RATE_KEYS:
            rate_key = header["key"]
        if not amount_key and key in _AMOUNT_KEYS:
            amount_key = header["key"]
    return rate_key, amount_key


def _pricing_by_row(display: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Aggregate priced output per BOQ row for the original sheet."""
    pricing: dict[str, dict[str, Any]] = {}
    for line in display.get("lines") or []:
        row_id = str(line.get("row_id") or "")
        if not row_id:
            continue

        material_total = Decimal("0")
        labour_total = Decimal("0")
        total_amount = Decimal("0")
        has_values = False

        for product in line.get("products") or []:
            line_output = product.get("line_output") or {}
            if line_output.get("is_blank"):
                continue
            material_amount = _to_decimal(line_output.get("material_amount"))
            labour_amount = _to_decimal(line_output.get("labour_amount"))
            row_total = _to_decimal(line_output.get("total_amount"))
            if material_amount is not None:
                material_total += material_amount
                has_values = True
            if labour_amount is not None:
                labour_total += labour_amount
                has_values = True
            if row_total is not None:
                total_amount += row_total
                has_values = True

        if not has_values:
            continue

        qty = _to_decimal(line.get("qty"))
        unit_rate = None
        if qty and qty != 0:
            unit_rate = total_amount / qty

        pricing[row_id] = {
            "rate": _format_decimal(unit_rate),
            "amount": _format_decimal(total_amount),
            "material_amount": _format_decimal(material_total),
            "labour_amount": _format_decimal(labour_total),
        }
    return pricing


class BOQExportService:
    """Write priced BOQ workbook with original sheet + charge breakdown."""

    def __init__(self, boq_id: int, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq_id = boq_id
        self.confirmations = confirmations or {}

    def run(self) -> tuple[bytes, str]:
        boq = BOQ.objects.get(pk=self.boq_id)
        display = BOQAnalysisDisplayService(boq, self.confirmations).build()
        if not display.get("has_analysis"):
            raise ValueError("Run Match before exporting.")

        boq_data = boq.boq_data or {}
        pricing = _pricing_by_row(display)

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
        logger.info("Exported BOQ workbook for id=%s (%s)", boq.pk, filename)
        return buffer.getvalue(), filename

    @staticmethod
    def _write_boq_sheet(
        sheet: Worksheet,
        boq_data: dict[str, Any],
        pricing: dict[str, dict[str, Any]],
    ) -> None:
        headers = boq_data.get("headers") or []
        rate_key, amount_key = _header_keys(headers)
        sheet.append([header.get("label") or header.get("key") or "" for header in headers])
        for cell in sheet[1]:
            cell.font = Font(bold=True)

        for row in boq_data.get("rows") or []:
            row_id = str(row.get("row_id") or "")
            row_values: dict[str, Any] = {}
            for header in headers:
                key = header.get("key")
                if not key:
                    continue
                row_values[key] = cell_value(row, key)

            priced = pricing.get(row_id)
            if priced:
                if rate_key:
                    row_values[rate_key] = priced.get("rate")
                if amount_key:
                    row_values[amount_key] = priced.get("amount")

            sheet.append([row_values.get(header.get("key")) for header in headers])

    @staticmethod
    def _write_breakdown_sheet(sheet: Worksheet, display: dict[str, Any]) -> None:
        sheet.append(_BREAKDOWN_HEADERS)
        for cell in sheet[1]:
            cell.font = Font(bold=True)

        for line in display.get("lines") or []:
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
                )
                continue

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
                        selected.get("sub_category") or product.get("extracted_sub_category"),
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
