"""Labour + accessories cost (Phase 7, Sprint 14).

Execution costs are expanded from the TOR ("template of rates") tables for the
matched product (docs/DATABASE_ARCHITECTURE.md - TOR tables):

    labour_cost      = sum(TOR_Labour.quantity x LabourMaster.labour_rate)
    accessories_cost = sum(TOR_Accessories.quantity x RateMaster.purchase_rate)

TOR rows are keyed by tor_code; the available join from a matched item is its
product_code, so we use tor_code == product_code. All deterministic - AI never
performs costing (docs/AGENTS.md - AI Rules).
"""
from __future__ import annotations

from decimal import Decimal

from utils.text import normalize


def labour_cost(product, labour_rates: dict, tor_labour_by_code: dict) -> Decimal:
    """Per-unit labour cost for a product from its TOR labour rows or direct LabourMaster prefix match."""
    if product is None:
        return Decimal("0.00")
    
    norm_code = normalize(product.product_code)
    
    # 1. Try standard TOR join first
    tor_rows = tor_labour_by_code.get(norm_code, [])
    if tor_rows:
        total = Decimal("0")
        for row in tor_rows:
            rate = labour_rates.get(normalize(row.labour_code))
            if rate is not None:
                total += Decimal(row.quantity) * Decimal(rate.labour_rate)
        return total

    # 2. Fallback: Direct lookup in labour_rates where the labour_code is a prefix of product_code
    # Sort by length desc so that the most specific prefix wins
    for l_code in sorted(labour_rates.keys(), key=len, reverse=True):
        if norm_code.startswith(l_code):
            rate = labour_rates[l_code]
            return Decimal(rate.labour_rate)

    return Decimal("0.00")


def accessories_cost(product, tor_accessories_by_code: dict, accessory_rates: dict) -> Decimal:
    """Per-unit accessories cost for a product from its TOR accessory rows or spec_json accessories_% override."""
    if product is None:
        return Decimal("0.00")
    
    norm_code = normalize(product.product_code)
    
    # 1. Try standard TOR join first
    tor_rows = tor_accessories_by_code.get(norm_code, [])
    if tor_rows:
        total = Decimal("0")
        for row in tor_rows:
            rate = accessory_rates.get(normalize(row.accessory_code))
            if rate is not None:
                total += Decimal(row.quantity) * Decimal(rate.purchase_rate)
        return total

    # 2. Fallback: Check if spec_json contains accessories percentage
    if hasattr(product, "spec_json") and product.spec_json:
        # Check various common keys
        keys = ["accessories", "accessories_percent", "accessories_value"]
        for key in keys:
            val = product.spec_json.get(key)
            if val is not None and val != "":
                try:
                    pct = Decimal(str(val))
                    # E.g. 0.15 for 15%
                    if 0 < pct < 1:
                        return product.purchase_rate * pct
                    # E.g. 15 for 15%
                    elif 1 <= pct <= 100:
                        return product.purchase_rate * (pct / Decimal("100"))
                except Exception:
                    pass

    return Decimal("0.00")
