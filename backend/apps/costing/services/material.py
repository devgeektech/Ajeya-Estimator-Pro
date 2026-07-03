"""Material cost (Phase 7, Sprint 13).

Per-unit material cost is the selected vendor's purchase rate
(docs/PRD.md - Internal Review Sheet: Purchase rate; Cost Calculation). The
vendor row is chosen in Sprint 12 and stored on the ProductMatch. Deterministic
- AI never performs costing (docs/AGENTS.md - AI Rules).
"""
from __future__ import annotations

from decimal import Decimal


def material_cost(product_match) -> Decimal:
    """Return the per-unit material cost for a matched item.

    Zero when no product/vendor is selected (e.g. pending products), so the row
    stays blank in output.
    """
    product = product_match.product
    if product is None:
        return Decimal("0.00")
    return Decimal(product.purchase_rate or 0)
