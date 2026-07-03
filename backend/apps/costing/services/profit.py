"""Commercial margins: overheads + profit (Phase 7, Sprint 15).

Rule-based percentages applied to the accumulated cost base
(docs/PRD.md - Cost Calculation). AI never performs these calculations
(docs/AGENTS.md - AI Rules).
"""
from __future__ import annotations

from decimal import Decimal

from common.constants import OVERHEAD_PERCENT, PROFIT_PERCENT


def overhead_cost(base: Decimal, product=None) -> Decimal:
    """Overhead as a percentage of the cost base. Fallback to product handling_% / overhead_% from spec_json."""
    pct = OVERHEAD_PERCENT
    if product and hasattr(product, "spec_json") and product.spec_json:
        val = product.spec_json.get("handling_%") or product.spec_json.get("handling_percent") or product.spec_json.get("overhead_%") or product.spec_json.get("overhead_percent")
        if val is not None and val != "":
            try:
                ov_pct = Decimal(str(val))
                if 0 < ov_pct < 1:
                    pct = ov_pct * Decimal("100")
                elif 1 <= ov_pct <= 100:
                    pct = ov_pct
            except Exception:
                pass
    return Decimal(base) * pct / Decimal("100")


def profit(base_with_overhead: Decimal, product=None) -> Decimal:
    """Profit as a percentage of the base including overhead. Fallback to product profit_% from spec_json."""
    pct = PROFIT_PERCENT
    if product and hasattr(product, "spec_json") and product.spec_json:
        val = product.spec_json.get("profit_%") or product.spec_json.get("profit_percent")
        if val is not None and val != "":
            try:
                pr_pct = Decimal(str(val))
                if 0 < pr_pct < 1:
                    pct = pr_pct * Decimal("100")
                elif 1 <= pr_pct <= 100:
                    pct = pr_pct
            except Exception:
                pass
    return Decimal(base_with_overhead) * pct / Decimal("100")
