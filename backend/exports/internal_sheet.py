"""Internal review sheet generation (Phase 10, Sprint 19).

Detailed per-row cost breakdown with confidence colour bands
(docs/PRD.md - Internal Review Sheet). Used internally only.
"""
from __future__ import annotations

from common.constants import confidence_band

from .formatter import band_fill, write_header

HEADERS = [
    "#", "Description", "Product", "Make", "Vendor", "Purchase Rate",
    "Labour", "Transportation", "Accessories", "Overheads", "Profit",
    "Final Rate", "Qty", "Amount", "Confidence",
]
FINAL_RATE_COL = 12  # column "L" - referenced by the client sheet


def _num(value) -> float:
    return float(value or 0)


def write_internal_sheet(ws, run) -> None:
    """Populate ``ws`` with the internal review breakdown for a run."""
    ws.title = "Internal Review"
    write_header(ws, HEADERS)

    row = 2
    for item in run.items.all().order_by("row_number"):
        match = item.product_matches.first()
        breakdown = getattr(match, "cost_breakdown", None) if match else None
        product = match.product if match else None
        qty = _num(item.quantity)
        final_rate = _num(breakdown.final_rate) if breakdown else 0.0

        values = [
            item.row_number,
            item.description,
            product.product_code if product else "",
            match.make if match else "",
            match.vendor if match else "",
            _num(breakdown.material_cost) if breakdown else 0.0,
            _num(breakdown.labour_cost) if breakdown else 0.0,
            _num(breakdown.transportation_cost) if breakdown else 0.0,
            _num(breakdown.accessories_cost) if breakdown else 0.0,
            _num(breakdown.overhead_cost) if breakdown else 0.0,
            _num(breakdown.profit) if breakdown else 0.0,
            final_rate,
            qty,
            round(final_rate * qty, 2),
            _num(match.confidence_score) if match else 0.0,
        ]
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)

        band = confidence_band(_num(match.confidence_score)) if match else "blank"
        ws.cell(row=row, column=len(HEADERS)).fill = band_fill(band)
        row += 1

    return None
