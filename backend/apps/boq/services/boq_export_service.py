"""Export confirmed BOQ analysis lines to Excel."""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from django.utils.text import slugify
from openpyxl import Workbook
from openpyxl.styles import Font

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_display_service import BOQAnalysisDisplayService

logger = logging.getLogger("boq_ai")

_HEADERS = [
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


class BOQExportService:
    """Write priced analysis lines to an Excel workbook."""

    def __init__(self, boq_id: int, confirmations: dict[str, dict[str, Any]] | None = None):
        self.boq_id = boq_id
        self.confirmations = confirmations or {}

    def run(self) -> tuple[bytes, str]:
        boq = BOQ.objects.get(pk=self.boq_id)
        display = BOQAnalysisDisplayService(boq, self.confirmations).build()
        if not display.get("has_analysis"):
            raise ValueError("Run Match before exporting.")

        workbook = Workbook()
        sheet = workbook.active
        if sheet is None:
            sheet = workbook.create_sheet("BOQ Analysis")
        else:
            sheet.title = "BOQ Analysis"
        sheet.append(_HEADERS)
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

        buffer = BytesIO()
        workbook.save(buffer)
        filename = f"{slugify(boq.boq_name) or 'boq'}-analysis.xlsx"
        logger.info("Exported BOQ analysis workbook for id=%s (%s)", boq.pk, filename)
        return buffer.getvalue(), filename
