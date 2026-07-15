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
    """Return taxonomy JSON for extraction prompts."""
    version = get_active_database_version()
    if version is None:
        return json.dumps(
            {
                "category_taxonomy": [],
                "categories": [],
                "sub_categories": [],
                "attribute_keys": [],
                "activities": list(_DEFAULT_ACTIVITIES),
            },
            ensure_ascii=False,
        )

    rows = Rate_Master.objects.filter(database_version=version).values_list(
        "Category",
        "Sub_Category",
        "Attribute",
    )
    taxonomy: dict[str, set[str]] = {}
    attribute_keys: set[str] = set()
    aliases: dict[str, str] = {}

    for category, sub_category, attribute in rows:
        category_text = str(category or "").strip()
        if not category_text:
            continue
        bucket = taxonomy.setdefault(category_text, set())
        sub_text = str(sub_category or "").strip()
        if sub_text:
            bucket.add(sub_text)
        parsed = parse_attributes(attribute)
        learn_aliases_from_attributes(parsed, aliases)
        attribute_keys.update(parsed.keys())

    payload = {
        "category_taxonomy": [
            {"category": category, "sub_categories": sorted(subs)}
            for category, subs in sorted(taxonomy.items())
        ],
        "categories": sorted(taxonomy.keys()),
        "sub_categories": sorted({sub for subs in taxonomy.values() for sub in subs}),
        "attribute_keys": sorted(attribute_keys),
        "activities": list(_DEFAULT_ACTIVITIES),
    }
    return json.dumps(payload, ensure_ascii=False)
