"""Breakdown list sheet generation (Phase 10, Sprint 19).

Detailed per-row breakdown list with confidence colour bands
(docs/PRD.md - Internal Review Sheet). Used internally only.
"""
from __future__ import annotations

from common.constants import confidence_band

from .formatter import band_fill, write_header

HEADERS = [
    "BOQ Ser No",
    "BOQ Description as in Original",
    "AI Interpretation",
    "DB_Ser No",
    "Approved _Make",
    "Supplier",
    "Base_Purchase_Rate",
    "Discount %",
    "Net Material Rate",
    "Commercial_Material_Base",
    "Accessories_Value",
    "Handling_Value",
    "Wastage_Value",
    "Subtotal_Before_Profit",
    "Profit_Value",
    "Final_Expenditure",
    "Final_Amount_(Excl GST)",
    "Margin_%_On_Selling",
    "Total_Labour_per_unit_with _labour _Multipler",
    "Confidence",
]
BREAKDOWN_SHEET_TITLE = "Breakdown List"
FINAL_RATE_COL = 17  # column "Q" - referenced by the client sheet


def _num(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _spec_value(spec: dict, *keys):
    for key in keys:
        if key in spec and spec[key] not in (None, ""):
            return spec[key]
    return ""


def _ai_interpretation(item) -> str:
    extraction = item.ai_extraction or {}
    products = extraction.get("products")
    if isinstance(products, list) and products:
        names = [
            str(product.get("product") or "").strip()
            for product in products
            if isinstance(product, dict) and product.get("product")
        ]
        if names:
            return "; ".join(names)
    parts = [
        extraction.get(field)
        for field in ("product", "size", "material", "make")
        if extraction.get(field)
    ]
    return " ".join(str(part) for part in parts)


def write_internal_sheet(ws, run) -> None:
    """Populate ``ws`` with the internal breakdown list for a run."""
    ws.title = BREAKDOWN_SHEET_TITLE
    write_header(ws, HEADERS)

    row = 2
    for item in run.items.all().order_by("row_number"):
        match = item.product_matches.first()
        breakdown = getattr(match, "cost_breakdown", None) if match else None
        product = match.product if match else None
        spec = product.spec_json if product and isinstance(product.spec_json, dict) else {}
        material_cost = _num(breakdown.material_cost) if breakdown else 0.0
        accessories_cost = _num(breakdown.accessories_cost) if breakdown else 0.0
        profit = _num(breakdown.profit) if breakdown else 0.0
        labour_cost = _num(breakdown.labour_cost) if breakdown else 0.0
        final_rate = _num(breakdown.final_rate) if breakdown else 0.0
        final_amount = _num(product.final_amount_excl_gst) if product else 0.0
        if not final_amount:
            final_amount = final_rate
        handling = _num(
            _spec_value(spec, "handling_value", "handling", "handling_charges")
        )
        wastage = _num(_spec_value(spec, "wastage_value", "wastage"))
        subtotal_before_profit = final_rate - profit

        values = [
            (item.original_data or {}).get("s_no", ""),
            item.description,
            _ai_interpretation(item),
            product.product_code if product else "",
            match.make if match else "",
            match.vendor if match else "",
            _num(product.purchase_rate) if product else 0.0,
            _spec_value(spec, "discount", "discount_percent", "discount_pct", "discount_%"),
            material_cost,
            _num(_spec_value(spec, "commercial_material_base")) or material_cost,
            accessories_cost,
            handling,
            wastage,
            subtotal_before_profit,
            profit,
            final_rate,
            final_amount,
            _spec_value(spec, "margin_%_on_selling", "margin_on_selling", "margin"),
            labour_cost,
            _num(match.confidence_score) if match else 0.0,
        ]
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)

        band = confidence_band(_num(match.confidence_score)) if match else "blank"
        ws.cell(row=row, column=len(HEADERS)).fill = band_fill(band)
        row += 1

    return None
