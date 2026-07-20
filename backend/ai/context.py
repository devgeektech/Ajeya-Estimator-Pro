"""Compact database context for AI extraction prompts."""
from __future__ import annotations

import json

from apps.database_manager.models import Rate_Master
from apps.database_manager.services.activation import get_active_database_version
from utils.attribute_parser import learn_aliases_from_attributes, parse_attributes

# Work activities for extraction — not Labour_Master.Labour_Type (ITEM_BASED / SIZE_BASED).
_DEFAULT_ACTIVITIES = [
    "Installation",
    "Testing",
    "Commissioning",
    "Fixing",
    "Fabrication",
    "Supply and installation",
]


def build_database_context() -> str:
    """Return compact taxonomy JSON for extraction prompts.

    Categories only (no full subcategory dump — lists are huge). Extract still
    outputs free-text ``sub_category`` from the BOQ; mapping reconciles later.
    """
    version = get_active_database_version()
    if version is None:
        return json.dumps(
            {
                "categories": [],
                "attribute_keys": [],
                "activities": list(_DEFAULT_ACTIVITIES),
            },
            ensure_ascii=False,
        )

    rows = Rate_Master.objects.filter(database_version=version).values_list(
        "Category",
        "Attribute",
    )
    categories: set[str] = set()
    attribute_keys: set[str] = set()
    aliases: dict[str, str] = {}

    for category, attribute in rows:
        category_text = str(category or "").strip()
        if category_text:
            categories.add(category_text)
        parsed = parse_attributes(attribute)
        learn_aliases_from_attributes(parsed, aliases)
        attribute_keys.update(parsed.keys())

    payload = {
        "categories": sorted(categories),
        "attribute_keys": sorted(attribute_keys),
        "activities": list(_DEFAULT_ACTIVITIES),
    }
    return json.dumps(payload, ensure_ascii=False)
