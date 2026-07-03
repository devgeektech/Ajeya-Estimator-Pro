"""Exact product matching (Phase 5, Sprint 10).

Highest-priority strategy (docs/DATABASE_ARCHITECTURE.md - Search Strategy):
matches a query against a RateMaster product_code or an exact (normalized)
description. No AI involved.
"""
from __future__ import annotations

from utils.text import normalize


def find_exact(query: str, rates) -> object | None:
    """Return the RateMaster whose code/description equals the query, else None.

    ``rates`` is an iterable of RateMaster rows (already scoped to the active
    database version).
    """
    target = normalize(query)
    if not target:
        return None
    for rate in rates:
        if normalize(rate.product_code) == target:
            return rate
        if normalize(rate.description) == target:
            return rate
    return None
