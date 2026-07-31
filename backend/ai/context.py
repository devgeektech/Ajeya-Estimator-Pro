"""Compact database context for AI extraction prompts."""
from __future__ import annotations

import json
import re
from typing import Any

from apps.database_manager.models import Rate_Master_Output
from apps.database_manager.services.activation import get_active_database_version
from utils.attribute_parser import learn_aliases_from_attributes, parse_attributes


def _normalize_label(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def load_rate_master_taxonomy(
    database_version_id: int | None = None,
) -> dict[str, Any]:
    """
    Return Rate_Master_Output taxonomy for the active (or given) database.

    Shape::
        {
          "categories": ["PIPE", ...],
          "sub_categories_by_category": {"PIPE": ["GI", "MS", ...], ...},
        }
    """
    version = None
    if database_version_id is not None:
        from apps.database_manager.models import DatabaseVersion

        version = DatabaseVersion.objects.filter(pk=database_version_id).first()
    else:
        version = get_active_database_version()

    if version is None:
        return {"categories": [], "sub_categories_by_category": {}}

    rows = Rate_Master_Output.objects.filter(database_version=version).values_list(
        "Category",
        "Sub_Category",
    )
    by_category: dict[str, set[str]] = {}
    for category, sub_category in rows:
        category_text = str(category or "").strip()
        if not category_text:
            continue
        by_category.setdefault(category_text, set())
        sub_text = str(sub_category or "").strip()
        if sub_text:
            by_category[category_text].add(sub_text)

    categories = sorted(by_category.keys())
    sub_categories_by_category = {
        category: sorted(by_category[category]) for category in categories
    }
    return {
        "categories": categories,
        "sub_categories_by_category": sub_categories_by_category,
    }


def resolve_category_label(hint: str, categories: list[str]) -> str | None:
    """Match a free-text hint onto an actual DB category label."""
    if not hint or not categories:
        return None
    hint_norm = _normalize_label(hint)
    by_norm = {_normalize_label(cat): cat for cat in categories}
    if hint_norm in by_norm:
        return by_norm[hint_norm]
    for cat_norm, cat in by_norm.items():
        if hint_norm == cat_norm or hint_norm in cat_norm or cat_norm in hint_norm:
            return cat
    return None


_SUB_CATEGORY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ms": ("mild steel", "m s", "m.s", "ms pipe"),
    "gi": ("galvanised", "galvanized", "g i", "g.i"),
    "ss": ("stainless", "stainless steel", "s s"),
    "ci": ("cast iron", "c i"),
    "di": ("ductile iron", "d i"),
}


def resolve_sub_category_label(
    hint: str,
    *,
    category: str | None,
    sub_categories_by_category: dict[str, list[str]],
) -> str | None:
    """Match a free-text hint onto a DB sub-category for the given category."""
    if not hint:
        return None
    hint_norm = _normalize_label(hint)
    if not hint_norm:
        return None

    candidates: list[str] = []
    if category and category in sub_categories_by_category:
        candidates = list(sub_categories_by_category.get(category) or [])
    else:
        # Fall back across all categories when category is unknown.
        seen: set[str] = set()
        for values in sub_categories_by_category.values():
            for value in values:
                if value not in seen:
                    seen.add(value)
                    candidates.append(value)

    if not candidates:
        return None

    by_norm = {_normalize_label(item): item for item in candidates}
    if hint_norm in by_norm:
        return by_norm[hint_norm]
    for sub_norm, sub in by_norm.items():
        if hint_norm == sub_norm or hint_norm in sub_norm or sub_norm in hint_norm:
            return sub

    # Synonym bridge (mild steel → MS, galvanised → GI, …).
    for sub_norm, sub in by_norm.items():
        synonyms = _SUB_CATEGORY_SYNONYMS.get(sub_norm) or ()
        if hint_norm in synonyms or any(token in hint_norm for token in synonyms):
            return sub
        if any(_normalize_label(token) == hint_norm for token in synonyms):
            return sub
    return None


def snap_product_taxonomy(
    product: dict[str, Any],
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snap product category/sub_category onto Rate_Master_Output labels."""
    taxonomy = taxonomy or load_rate_master_taxonomy()
    categories = list(taxonomy.get("categories") or [])
    by_category = dict(taxonomy.get("sub_categories_by_category") or {})
    item = dict(product)

    raw_category = item.get("category")
    if raw_category not in (None, ""):
        resolved = resolve_category_label(str(raw_category), categories)
        if resolved:
            item["category"] = resolved

    category = str(item.get("category") or "").strip() or None
    raw_sub = item.get("sub_category")
    if raw_sub not in (None, ""):
        resolved_sub = resolve_sub_category_label(
            str(raw_sub),
            category=category,
            sub_categories_by_category=by_category,
        )
        if resolved_sub:
            item["sub_category"] = resolved_sub
    return item


def align_product_taxonomy_from_db_labels(
    product: dict[str, Any],
    *,
    category: Any = None,
    sub_category: Any = None,
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Align extracted taxonomy with matched Rate_Master_Output labels."""
    item = dict(product)
    if category not in (None, ""):
        item["category"] = str(category).strip()
    if sub_category not in (None, ""):
        item["sub_category"] = str(sub_category).strip()
    return snap_product_taxonomy(item, taxonomy)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def fill_product_core_fields_from_rate(
    product: dict[str, Any],
    rate: Rate_Master_Output,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Copy core Rate_Master_Output identity fields onto the extracted product.

    Analysis owns product identity (not make). Blank fields are always filled.
    When ``overwrite`` is True (confirmed DB match), replace AI values that
    disagree with the matched Rate_Master_Output row so experts need not Re-analyse
    only to pick up DB class/size/unit/capacity.
    """
    item = dict(product)

    def _as_text(raw: Any) -> str:
        if raw in (None, ""):
            return ""
        if hasattr(raw, "normalize"):
            try:
                normalized = raw.normalize()
                text = format(normalized, "f")
                if "." in text:
                    text = text.rstrip("0").rstrip(".")
                return text
            except Exception:
                return str(raw).strip()
        return str(raw).strip()

    mappings = (
        ("class", rate.Class),
        ("size", rate.Size),
        ("unit", rate.Unit),
        ("capacity", rate.Capacity),
    )
    for field, raw in mappings:
        value = _as_text(raw)
        if not value:
            continue
        if overwrite or _is_blank(item.get(field)):
            item[field] = value
    # Make selection belongs to Make & Vendor — clear analysis make hints.
    item["make_hint"] = None
    return item


def align_product_taxonomy_from_rate(
    product: dict[str, Any],
    rate: Rate_Master_Output,
    *,
    taxonomy: dict[str, Any] | None = None,
    overwrite_core_fields: bool = False,
) -> dict[str, Any]:
    """Set product taxonomy and core fields from a Rate_Master_Output row."""
    item = align_product_taxonomy_from_db_labels(
        product,
        category=rate.Category,
        sub_category=rate.Sub_Category,
        taxonomy=taxonomy,
    )
    return fill_product_core_fields_from_rate(
        item,
        rate,
        overwrite=overwrite_core_fields,
    )


def build_database_context() -> str:
    """Return compact taxonomy JSON for extraction prompts (categories + sub-categories)."""
    taxonomy = load_rate_master_taxonomy()
    version = get_active_database_version()
    if version is None:
        return json.dumps(
            {
                "categories": [],
                "sub_categories_by_category": {},
                "attribute_keys": [],
            },
            ensure_ascii=False,
        )

    rows = Rate_Master_Output.objects.filter(database_version=version).values_list(
        "Attribute",
        flat=True,
    )
    attribute_keys: set[str] = set()
    aliases: dict[str, str] = {}
    for attribute in rows:
        parsed = parse_attributes(attribute)
        learn_aliases_from_attributes(parsed, aliases)
        attribute_keys.update(parsed.keys())

    payload = {
        "categories": taxonomy.get("categories") or [],
        "sub_categories_by_category": taxonomy.get("sub_categories_by_category") or {},
        "attribute_keys": sorted(attribute_keys),
    }
    return json.dumps(payload, ensure_ascii=False)
