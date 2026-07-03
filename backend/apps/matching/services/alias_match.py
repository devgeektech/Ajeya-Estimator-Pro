"""Alias product matching (Phase 5, Sprint 10).

Second-priority strategy (docs/DATABASE_ARCHITECTURE.md - Search Strategy):
maps a known alias (e.g. '150 NB Pipe', 'ERW Pipe') to a product_code and
resolves it within the active database version. No AI involved.
"""
from __future__ import annotations

from utils.text import normalize


def find_alias(query: str, rates_by_code: dict) -> object | None:
    """Return a RateMaster matched via ProductAlias, else None.

    ``rates_by_code`` maps normalized product_code -> RateMaster for the active
    version. The longest matching alias wins to prefer the most specific entry.
    """
    from apps.database_manager.models import ProductAlias

    target = normalize(query)
    if not target:
        return None

    best_code: str | None = None
    best_len = 0
    for alias in ProductAlias.objects.all():
        alias_norm = normalize(alias.alias)
        if not alias_norm:
            continue
        if (alias_norm == target or alias_norm in target) and len(alias_norm) > best_len:
            code = normalize(alias.product_code)
            if code in rates_by_code:
                best_code = code
                best_len = len(alias_norm)

    return rates_by_code.get(best_code) if best_code else None
