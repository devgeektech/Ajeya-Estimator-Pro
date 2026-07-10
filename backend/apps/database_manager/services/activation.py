"""Ensure exactly one DatabaseVersion is active at a time."""

from __future__ import annotations

import logging

from django.db import transaction

from ..models import DatabaseVersion

logger = logging.getLogger("boq_ai")


def _clear_database_context_cache() -> None:
    from ai.context import clear_database_context_cache

    clear_database_context_cache()


def activate_database_version(version: DatabaseVersion) -> DatabaseVersion:
    """Mark one database version active and deactivate all others."""
    with transaction.atomic():
        DatabaseVersion.objects.exclude(pk=version.pk).update(is_active=False)
        if not version.is_active:
            version.is_active = True
            version.save(update_fields=["is_active"])
    _clear_database_context_cache()
    logger.info("Activated database v%s", version.version_number)
    return version


def repair_duplicate_active_versions() -> int:
    """Keep the highest version_number active when multiple are flagged active."""
    active_versions = list(
        DatabaseVersion.objects.filter(is_active=True).order_by(
            "-version_number", "-uploaded_at", "-pk"
        )
    )
    if len(active_versions) <= 1:
        return 0

    keep = active_versions[0]
    stale_ids = [version.pk for version in active_versions[1:]]
    deactivated = DatabaseVersion.objects.filter(pk__in=stale_ids).update(is_active=False)
    _clear_database_context_cache()
    logger.warning(
        "Repaired %s duplicate active database version(s); kept v%s active",
        deactivated,
        keep.version_number,
    )
    return deactivated


def get_active_database_version() -> DatabaseVersion | None:
    """Return the single active database version, repairing duplicates if needed."""
    repair_duplicate_active_versions()
    return DatabaseVersion.objects.filter(is_active=True).order_by(
        "-version_number", "-uploaded_at", "-pk"
    ).first()
