"""Compact database context for AI extraction prompts."""

from __future__ import annotations

import json
import re

from django.core.cache import cache

from apps.database_manager.models import (
    DatabaseVersion,
    LabourConfig,
    LabourMaster,
    MaterialRate,
)
from apps.database_manager.services.activation import get_active_database_version

NO_DATABASE_CONTEXT_CACHE_KEY = "ai:database_context:none"
DATABASE_CONTEXT_CACHE_EPOCH_KEY = "ai:database_context:epoch"
INTERNAL_LABOUR_TYPES = frozenset({"size_based", "item_based"})
TOR_ACTIVITY_NAMES = ("testing", "scaffolding", "consumables", "painting")
TECH_KEY_PATTERN = re.compile(r"^[A-Z0-9_]+$")


def _cache_key(version_id: int) -> str:
    epoch = _context_epoch()
    return f"ai:database_context:e{epoch}:v{version_id}:taxonomy_v2"


def _context_epoch() -> int:
    epoch = cache.get(DATABASE_CONTEXT_CACHE_EPOCH_KEY)
    if epoch is None:
        epoch = 1
        cache.set(DATABASE_CONTEXT_CACHE_EPOCH_KEY, epoch, timeout=None)
    return int(epoch)


def clear_database_context_cache() -> None:
    """Invalidate cached AI database context after active DB changes."""
    try:
        cache.incr(DATABASE_CONTEXT_CACHE_EPOCH_KEY)
    except ValueError:
        cache.set(DATABASE_CONTEXT_CACHE_EPOCH_KEY, 2, timeout=None)
    cache.delete(NO_DATABASE_CONTEXT_CACHE_KEY)


def _unique_ordered(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _category_taxonomy(version: DatabaseVersion) -> list[dict]:
    """Map each Rate_Master category to its valid sub_categories."""
    rates = (
        MaterialRate.objects.filter(database_version=version)
        .exclude(Category__isnull=True)
        .exclude(Category="")
        .values_list("Category", "Sub_Category")
        .order_by("Category", "Sub_Category")
    )
    taxonomy: dict[str, list[str]] = {}
    for category, sub_category in rates:
        category_text = str(category or "").strip()
        if not category_text:
            continue
        bucket = taxonomy.setdefault(category_text, [])
        sub_text = str(sub_category or "").strip()
        if sub_text and sub_text not in bucket:
            bucket.append(sub_text)
    return [
        {"category": category, "sub_categories": sub_categories}
        for category, sub_categories in sorted(taxonomy.items())
    ]


def _is_internal_labour_type(value: str) -> bool:
    return value.strip().casefold() in INTERNAL_LABOUR_TYPES


def _looks_like_tech_key(value: str) -> bool:
    text = value.strip()
    return bool(text and TECH_KEY_PATTERN.fullmatch(text))


def _database_activities(version: DatabaseVersion) -> list[str]:
    """Return human-readable labour activity names for extraction prompts."""
    labour_types = _unique_ordered(
        LabourMaster.objects.filter(database_version=version)
        .exclude(Labour_Type__isnull=True)
        .exclude(Labour_Type="")
        .order_by("Labour_Type")
        .values_list("Labour_Type", flat=True)
    )
    activities: list[str] = []
    for labour_type in labour_types:
        if _is_internal_labour_type(labour_type) or _looks_like_tech_key(labour_type):
            continue
        activities.append(labour_type)
    if LabourConfig.objects.filter(database_version=version).exists():
        activities.extend(TOR_ACTIVITY_NAMES)
    return _unique_ordered(activities)


def build_database_context() -> str:
    """Return compact active-database taxonomy JSON for extraction prompts.

    Sends category/sub_category relationships plus labour activity names so the
    model can map BOQ text to the correct database vocabulary.
    """
    version = get_active_database_version()
    if version is None:
        cached = cache.get(NO_DATABASE_CONTEXT_CACHE_KEY)
        if cached is not None:
            return cached
        payload = {
            "category_taxonomy": [],
            "categories": [],
            "sub_categories": [],
            "activities": [],
        }
        context = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        cache.set(NO_DATABASE_CONTEXT_CACHE_KEY, context, timeout=60)
        return context

    cache_key = _cache_key(version.pk)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    category_taxonomy = _category_taxonomy(version)
    categories = _unique_ordered(
        entry["category"] for entry in category_taxonomy
    )
    sub_categories = _unique_ordered(
        sub_category
        for entry in category_taxonomy
        for sub_category in entry["sub_categories"]
    )
    activities = _database_activities(version)
    payload = {
        "category_taxonomy": category_taxonomy,
        "categories": categories,
        "sub_categories": sub_categories,
        "activities": activities,
    }
    context = json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )
    cache.set(cache_key, context, timeout=60 * 60)
    return context
