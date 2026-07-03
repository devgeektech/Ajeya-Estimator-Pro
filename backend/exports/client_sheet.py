"""Client sheet generation (Phase 10, Sprint 19).

Original BOQ format with final approved rates and amounts
(docs/PRD.md - Client Sheet). When generated alongside the internal sheet the
rate/amount cells are Excel formulas linked to the internal sheet so edits there
flow through ("Values are linked to the internal sheet"); as a standalone client
file the values are computed.
"""
from __future__ import annotations

from .formatter import write_header
from .internal_sheet import FINAL_RATE_COL

HEADERS = ["#", "Description", "Qty", "Unit", "Final Rate", "Amount"]


def _num(value) -> float:
    return float(value or 0)


def write_client_sheet(ws, run, *, link_sheet: str | None = None) -> None:
    """Populate ``ws`` with the client BOQ.

    If ``link_sheet`` is the internal sheet's title, the Final Rate / Amount
    cells reference it via formulas; otherwise computed values are written.
    """
    ws.title = "Client BOQ"
    write_header(ws, HEADERS)

    col_letter = chr(ord("A") + FINAL_RATE_COL - 1)  # internal Final Rate column
    row = 2
    for item in run.items.all().order_by("row_number"):
        match = item.product_matches.first()
        breakdown = getattr(match, "cost_breakdown", None) if match else None
        qty = _num(item.quantity)
        final_rate = _num(breakdown.final_rate) if breakdown else 0.0

        ws.cell(row=row, column=1, value=item.row_number)
        ws.cell(row=row, column=2, value=item.description)
        ws.cell(row=row, column=3, value=qty)
        ws.cell(row=row, column=4, value=item.unit)

        if link_sheet:
            ref = f"'{link_sheet}'!{col_letter}{row}"
            ws.cell(row=row, column=5, value=f"={ref}")
            ws.cell(row=row, column=6, value=f"={ref}*C{row}")
        else:
            ws.cell(row=row, column=5, value=final_rate)
            ws.cell(row=row, column=6, value=round(final_rate * qty, 2))
        row += 1

    return None
