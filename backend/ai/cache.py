"""Per-BOQ Redis cache helpers for AI completion results.

Cache is scoped per BOQ so that:
- The same section re-extracted in the same BOQ gets a cache hit.
- Deleting a BOQ clears all its cached AI results.
- Upgrading the master DB (new db_version_id) automatically invalidates results
  (the version is part of the key prefix).

Cache is DISABLED when AI_EXTRACT_CACHE_ENABLED is False or Redis is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("boq_ai")

# Prefix avoids collisions with other Django cache entries.
_CACHE_PREFIX = "boq_ai_extract"


def _cache_enabled() -> bool:
    return bool(getattr(settings, "AI_EXTRACT_CACHE_ENABLED", True))


def _default_ttl() -> int:
    return max(1, int(getattr(settings, "AI_EXTRACT_CACHE_TTL", 604800) or 604800))


def _payload_hash(payload: str) -> str:
    """SHA-256 of the raw payload string — used as the section fingerprint."""
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:32]


def make_extract_cache_key(
    boq_id: int | str,
    payload_json: str,
    db_version_id: int | str | None = None,
) -> str:
    """Build a per-BOQ, DB-version-scoped cache key for an extract payload.

    Key format: boq_ai_extract:v<db_version>:boq<boq_id>:<hash>
    Different db_version_id means a different master DB — those results are
    automatically distinct (no invalidation needed across DB upgrades).
    """
    version_part = str(db_version_id or "0")
    hash_part = _payload_hash(payload_json)
    return f"{_CACHE_PREFIX}:v{version_part}:boq{boq_id}:{hash_part}"


def make_taxonomy_cache_key(
    boq_id: int | str,
    description_hint: str,
    category: str,
) -> str:
    """Cache key for infer_taxonomy AI calls (scoped per BOQ)."""
    fingerprint = _payload_hash(f"{description_hint}|{category}")
    return f"{_CACHE_PREFIX}:taxonomy:boq{boq_id}:{fingerprint}"


def get_ai_cached(key: str) -> dict[str, Any] | None:
    """Return cached AI result dict or None on miss / disabled / error."""
    if not _cache_enabled():
        return None
    try:
        value = cache.get(key)
        if value is not None:
            logger.debug("AI cache HIT key=%s", key[-24:])
        return value
    except Exception:
        logger.warning("AI cache GET failed for key=%s", key[-24:], exc_info=False)
        return None


def set_ai_cached(key: str, value: dict[str, Any], ttl: int | None = None) -> None:
    """Store AI result dict in cache; silently skips on error."""
    if not _cache_enabled():
        return
    try:
        cache.set(key, value, timeout=ttl if ttl is not None else _default_ttl())
        logger.debug("AI cache SET key=%s ttl=%s", key[-24:], ttl or _default_ttl())
    except Exception:
        logger.warning("AI cache SET failed for key=%s", key[-24:], exc_info=False)


def clear_boq_extract_cache(boq_id: int | str) -> None:
    """Best-effort cache clear for all entries belonging to one BOQ.

    Django's default cache (Redis) supports key pattern deletion via
    cache.delete_pattern when django-redis is used. Falls back gracefully
    when pattern deletion is not available (e.g. LocMemCache in tests).
    """
    if not _cache_enabled():
        return
    pattern = f"{_CACHE_PREFIX}:*:boq{boq_id}:*"
    try:
        if hasattr(cache, "delete_pattern"):
            deleted = cache.delete_pattern(pattern)
            logger.info(
                "AI cache cleared for BOQ id=%s pattern=%s deleted=%s",
                boq_id,
                pattern,
                deleted,
            )
        else:
            # LocMemCache / non-Redis: no pattern support — log and continue.
            logger.debug(
                "AI cache clear skipped (no pattern support) for BOQ id=%s", boq_id
            )
    except Exception:
        logger.warning(
            "AI cache clear failed for BOQ id=%s", boq_id, exc_info=False
        )
