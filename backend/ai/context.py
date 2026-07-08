"""Compact database context for AI extraction prompts."""

from __future__ import annotations

import json

from django.core.cache import cache

from apps.database_manager.models import (
    DatabaseVersion,
    LabourMaster,
    RateMaster,
    TORLabour,
)


RATE_CONTEXT_FIELDS = (
    "category",
    "sub_category",
    "class",
    "size_mm",
    "make",
    "capacity",
    "unit",
    "supplier",
    "height",
    "working_pressure",
    "test_pressure",
    "temperature",
    "throw_distance",
    "k_factor",
    "head",
)
NO_DATABASE_CONTEXT_CACHE_KEY = "ai:database_context:none"
DATABASE_CONTEXT_CACHE_EPOCH_KEY = "ai:database_context:epoch"


def _cache_key(version_id: int, limit: int) -> str:
    epoch = _context_epoch()
    return f"ai:database_context:e{epoch}:v{version_id}:limit{limit}"


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


def _unique(values, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def build_database_context(limit: int = 80) -> str:
    """Return active database vocabulary as JSON for extraction prompts."""
    version = DatabaseVersion.objects.filter(is_active=True).first()
    if version is None:
        cached = cache.get(NO_DATABASE_CONTEXT_CACHE_KEY)
        if cached is not None:
            return cached
        payload = {"rate_master_vocabulary": [], "activities": []}
        context = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        cache.set(NO_DATABASE_CONTEXT_CACHE_KEY, context, timeout=60)
        return context

    cache_key = _cache_key(version.pk, limit)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    rates = RateMaster.objects.filter(database_version=version).order_by("tech_key")
    rate_context = []
    seen_rate_rows: set[tuple[str, ...]] = set()
    for rate in rates:
        row = {
            "category": rate.category,
            "sub_category": rate.sub_category,
            "class": rate.product_class,
            "size_mm": rate.size_mm,
            "make": rate.make,
            "capacity": rate.capacity,
            "unit": rate.unit,
            "supplier": rate.supplier,
            "height": rate.height,
            "working_pressure": rate.working_pressure,
            "test_pressure": rate.test_pressure,
            "temperature": rate.temperature,
            "throw": rate.throw_distance,
            "k_factor": rate.k_factor,
            "head": rate.head,
        }
        cleaned = {
            key: str(value).strip()
            for key, value in row.items()
            if str(value or "").strip()
        }
        if not cleaned:
            continue
        identity = tuple(
            cleaned.get(field, "").lower() for field in RATE_CONTEXT_FIELDS
        )
        if identity in seen_rate_rows:
            continue
        seen_rate_rows.add(identity)
        rate_context.append(cleaned)
        if len(rate_context) >= limit:
            break
    activity_values = list(
        LabourMaster.objects.filter(database_version=version).values_list(
            "labour_type", flat=True
        )
    ) + list(
        LabourMaster.objects.filter(database_version=version).values_list(
            "tech_key", flat=True
        )
    )
    if TORLabour.objects.filter(database_version=version).exists():
        activity_values.extend(["testing", "scaffolding", "consumables", "painting"])
    activities = _unique(activity_values, limit)
    payload = {
        "rate_master_vocabulary": rate_context,
        "activities": activities,
    }
    context = json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    cache.set(cache_key, context, timeout=60 * 60)
    return context
