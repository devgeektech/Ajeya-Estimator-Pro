"""Shared attribute field helpers for extraction UI."""
from __future__ import annotations

# Legacy static keys kept only for reading older saved forms / analysis payloads.
COMMON_ATTRIBUTE_FIELDS: tuple[tuple[str, str], ...] = (
    ("is", "IS Standard"),
    ("mounting", "Mounting"),
    ("material", "Material"),
    ("type", "Type"),
    ("outlet_type", "Outlet type"),
    ("pressure_rating", "Pressure rating"),
    ("connection_type", "Connection type"),
    ("fire_rating", "Fire rating"),
)

COMMON_ATTRIBUTE_KEYS = {key for key, _label in COMMON_ATTRIBUTE_FIELDS}

COMMON_ATTRIBUTE_LABELS = {key: label for key, label in COMMON_ATTRIBUTE_FIELDS}
