"""Exact product matching (Phase 5, Sprint 10).

Highest-priority strategy (docs/DATABASE_ARCHITECTURE.md - Search Strategy):
matches a query against a RateMaster product_code or an exact (normalized)
description. No AI involved.
"""
from __future__ import annotations

from utils.text import normalize


def selection_amount(rate):
    """Amount used when multiple RateMaster rows match the same product."""
    value = getattr(rate, "final_amount_excl_gst", None)
    return value if value not in (None, 0) else getattr(rate, "purchase_rate", 0)


def find_exact(query: str, rates) -> object | None:
    """Return the RateMaster whose code/description equals the query, else None.

    ``rates`` is an iterable of RateMaster rows (already scoped to the active
    database version).
    """
    target = normalize(query)
    if not target:
        return None
    matches = [
        rate
        for rate in rates
        if normalize(rate.product_code) == target or normalize(rate.description) == target
    ]
    if not matches:
        return None
    return min(matches, key=selection_amount)
