"""Exact product matching (Phase 5, Sprint 10).

Highest-priority strategy (docs/DATABASE_ARCHITECTURE.md - Search Strategy):
matches a query against RateMaster key/specification fields. No AI involved.
"""
from __future__ import annotations

from utils.text import normalize

IGNORED_QUERY_TOKENS = {
    "nb",
    "mm",
    "m",
    "nos",
    "no",
    "supply",
    "fixing",
    "installation",
    "and",
    "of",
    "as",
    "per",
    "specification",
    "specifications",
}


def selection_amount(rate):
    """Amount used when multiple RateMaster rows match the same product."""
    value = getattr(rate, "final_amount_excl_gst", None)
    return value if value not in (None, 0) else getattr(rate, "net_material_rate", 0)


def _rate_text(rate) -> str:
    return " ".join(
        str(value)
        for value in (
            rate.tech_key,
            rate.category,
            rate.sub_category,
            rate.product_class,
            rate.size_mm,
            rate.make,
            rate.capacity,
            rate.unit,
            rate.supplier,
        )
        if value
    )


def find_exact(query: str, rates) -> object | None:
    """Return the RateMaster whose key/specification equals the query, else None.

    ``rates`` is an iterable of RateMaster rows (already scoped to the active
    database version).
    """
    target = normalize(query)
    if not target:
        return None
    matches = []
    for rate in rates:
        haystack = normalize(_rate_text(rate))
        if target in {normalize(getattr(rate, "tech_key", "")), haystack}:
            matches.append(rate)
            continue
        query_tokens = _significant_tokens(target)
        haystack_tokens = {_token_key(token) for token in haystack.split()}
        if query_tokens and query_tokens.issubset(haystack_tokens):
            matches.append(rate)
    if not matches:
        return None
    return min(matches, key=selection_amount)


def _significant_tokens(text: str) -> set[str]:
    tokens = {
        _token_key(token)
        for token in normalize(text).split()
        if token and token not in IGNORED_QUERY_TOKENS
    }
    return tokens


def _token_key(token: str) -> str:
    if token.endswith(".00"):
        return token[:-3]
    return token
