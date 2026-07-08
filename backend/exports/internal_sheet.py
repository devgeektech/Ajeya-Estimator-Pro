"""Breakdown list sheet generation (Phase 10, Sprint 19).

Detailed per-row breakdown list with confidence colour bands
(docs/PRD.md - Internal Review Sheet). Used internally only.
"""
from __future__ import annotations

from common.constants import confidence_band

from .formatter import band_fill, write_header

HEADERS = [
    "BOQ Ser No",
    "Source Excel Row",
    "Target Excel Row",
    "BOQ Description as in Original",
    "AI Interpretation",
    "Extraction Index",
    "Extracted Product",
    "DB_Ser No",
    "Rate_Master ID",
    "Match Type",
    "Approved _Make",
    "Supplier",
    "Product Quantity",
    "Product Unit",
    "Quantity Basis",
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
    "Rate Contribution",
    "Margin_%_On_Selling",
    "Tech Key",
    "Total_Labour_per_unit_with _labour _Multipler",
    "Confidence",
    "Review Required",
    "Missing Product",
]
BREAKDOWN_SHEET_TITLE = "Breakdown List"
FINAL_RATE_COL = 27  # "Rate Contribution" - referenced by the client sheet


def _num(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ai_interpretation(item) -> str:
    extraction = item.ai_extraction or {}
    products = _extracted_candidates(extraction)
    if products:
        names = [
            str(product.get("product_name") or product.get("sub_category") or "").strip()
            for product in products
            if isinstance(product, dict)
        ]
        if names:
            return "; ".join(names)
    parts = [
        extraction.get(field)
        for field in ("product", "size", "material", "make")
        if extraction.get(field)
    ]
    return " ".join(str(part) for part in parts)


def _extracted_candidates(extraction: dict) -> list[dict]:
    products: list[dict] = []
    if isinstance(extraction, dict):
        for key in ("database_products", "missing_products"):
            values = extraction.get(key)
            if isinstance(values, list):
                products.extend(product for product in values if isinstance(product, dict))
    return products


def _candidate_for_match(item, match) -> dict:
    extraction = item.ai_extraction or {}
    products = _extracted_candidates(extraction)
    index = getattr(match, "extraction_index", 0) if match else 0
    if 0 <= index < len(products):
        return products[index]
    return {}


def _ai_interpretation_for_match(item, match) -> str:
    product = _candidate_for_match(item, match)
    if product:
        parts = [
            product.get(field)
            for field in ("category", "sub_category", "class", "size_mm", "make", "capacity")
            if product.get(field)
        ]
        if parts:
            return " ".join(str(part) for part in parts)
    return _ai_interpretation(item)


def _write_match_row(ws, row: int, item, match) -> None:
    detail = getattr(match, "rate_detail", None) if match else None
    product = match.product if match else None
    candidate = _candidate_for_match(item, match)
    final_amount = _num(detail.final_amount_excl_gst) if detail else 0.0
    rate_contribution = _num(detail.rate_contribution) if detail else 0.0

    values = [
        (item.original_data or {}).get("s_no", ""),
        item.row_number,
        item.target_excel_row or item.row_number,
        item.description,
        _ai_interpretation_for_match(item, match),
        match.extraction_index if match else "",
        candidate.get("product_name") or candidate.get("sub_category") or "",
        product.tech_key if product else "",
        product.pk if product else "",
        (match.match_type or match.match_reason) if match else "no_match",
        match.make if match else "",
        (product.supplier if product else "") or (match.supplier if match else ""),
        _num(match.product_quantity) if match else 0.0,
        match.product_unit if match else "",
        match.quantity_basis if match else "",
        _num(detail.base_purchase_rate) if detail else 0.0,
        _num(detail.discount_percent) if detail else 0.0,
        _num(detail.net_material_rate) if detail else 0.0,
        _num(detail.commercial_material_base) if detail else 0.0,
        _num(detail.accessories_value) if detail else 0.0,
        _num(detail.handling_value) if detail else 0.0,
        _num(detail.wastage_value) if detail else 0.0,
        _num(detail.subtotal_before_profit) if detail else 0.0,
        _num(detail.profit_value) if detail else 0.0,
        _num(detail.final_expenditure) if detail else 0.0,
        final_amount,
        rate_contribution,
        _num(detail.margin_percent_on_selling) if detail else 0.0,
        detail.tech_key if detail else (product.tech_key if product else ""),
        _num(detail.total_labour_with_multiplier) if detail else 0.0,
        _num(match.confidence_score) if match else 0.0,
        bool(match.review_required) if match else True,
        not bool(product),
    ]
    for col, value in enumerate(values, start=1):
        ws.cell(row=row, column=col, value=value)

    band = confidence_band(_num(match.confidence_score)) if match else "blank"
    ws.cell(row=row, column=len(HEADERS)).fill = band_fill(band)


def write_internal_sheet(ws, run) -> None:
    """Populate ``ws`` with the internal breakdown list for a run."""
    ws.title = BREAKDOWN_SHEET_TITLE
    write_header(ws, HEADERS)

    row = 2
    for item in run.items.all().order_by("row_number"):
        matches = list(item.product_matches.all())
        if not matches:
            _write_match_row(ws, row, item, None)
            row += 1
            continue
        for match in matches:
            _write_match_row(ws, row, item, match)
            row += 1

    return None
