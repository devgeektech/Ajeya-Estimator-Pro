"""Split slash-separated approved makes into individual tokens."""
from __future__ import annotations

import re
from typing import Any

_MAKE_SPLIT_PATTERN = re.compile(r"\s*/\s*")


def split_make_token(value: Any) -> list[str]:
    """Split one cell value into make tokens (e.g. ``TATA/JINDAL/SURYA``)."""
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in _MAKE_SPLIT_PATTERN.split(text) if part.strip()]


def collect_approved_makes(row: dict) -> list[str]:
    """Collect de-duplicated approved makes from all make columns on one row."""
    source = row.get("display_values") or row.get("values") or {}
    makes: list[str] = []
    seen: set[str] = set()

    for key in sorted(source):
        if not str(key).startswith("approved_makes"):
            continue
        for token in split_make_token(source.get(key)):
            fold = token.casefold()
            if fold in seen:
                continue
            seen.add(fold)
            makes.append(token)

    return makes


def attach_approved_makes_list(rows: list[dict]) -> list[dict]:
    """Attach ``approved_makes_list`` to each make-list row."""
    enriched: list[dict] = []
    for row in rows:
        approved_makes_list = collect_approved_makes(row)
        enriched.append({**row, "approved_makes_list": approved_makes_list})
    return enriched
