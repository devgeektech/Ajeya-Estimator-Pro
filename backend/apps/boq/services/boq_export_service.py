"""Export confirmed BOQ analysis to a two-sheet Excel workbook."""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils.text import slugify
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_display_service import BOQAnalysisDisplayService
from apps.boq.services.boq_price_calculation_service import build_row_pricing
from apps.boq.services.serial_normalizer import cell_value
from common.choices import BOQStatus

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


def _header_keys(headers: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    rate_key = amount_key = None
    for header in headers:
        key = str(header.get("key") or "").lower()
        if not rate_key and key in _RATE_KEYS:
            rate_key = header["key"]
        if not amount_key and key in _AMOUNT_KEYS:
            amount_key = header["key"]
    return rate_key, amount_key


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
            raise ValueError("Calculate Price before exporting.")

        display = BOQAnalysisDisplayService(boq, self.confirmations).build()
        if not display.get("has_analysis"):
            raise ValueError("Run Match before exporting.")

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
