"""Ensure exactly one DatabaseVersion is active at a time."""

from __future__ import annotations

import logging

from common.db import atomic

from common.constants import DATABASE_UPLOADS_TO_RETAIN

from ..models import MASTER_DATA_MODELS, DatabaseVersion

logger = logging.getLogger("boq_ai")


def purge_inactive_master_data(active: DatabaseVersion) -> int:
    """Remove PostgreSQL master rows for every version except the active one.

    ``DatabaseVersion`` records and stored workbooks are kept so users can still
    view upload history and download archived sheets.
    """
    from ai.embeddings.chroma_store import ChromaEmbeddingStore

    inactive_ids = list(
        DatabaseVersion.objects.exclude(pk=active.pk).values_list("pk", flat=True)
    )
    if not inactive_ids:
        return 0

    store = ChromaEmbeddingStore()
    rows_removed = 0
    for version_id in inactive_ids:
        store.reset_version(version_id)
        for model in MASTER_DATA_MODELS:
            deleted, _ = model.objects.filter(database_version_id=version_id).delete()
            rows_removed += deleted

    logger.info(
        "Purged master data from %s inactive database version(s); active v%s retained",
        len(inactive_ids),
        active.version_number,
    )
    return rows_removed


def enforce_version_retention() -> int:
    """Drop oldest upload records (and workbooks) beyond the retention limit."""
    versions = list(DatabaseVersion.objects.order_by("-version_number"))
    if len(versions) <= DATABASE_UPLOADS_TO_RETAIN:
        return 0

    stale = versions[DATABASE_UPLOADS_TO_RETAIN:]
    stale_ids = [version.pk for version in stale]

    for version in stale:
        file_field = version.file
        if file_field and file_field.name:
            try:
                file_field.delete(save=False)
            except OSError:
                logger.warning(
                    "Could not delete workbook file for database v%s",
                    version.version_number,
                )

    DatabaseVersion.objects.filter(pk__in=stale_ids).delete()
    logger.info("Retention: removed %s old database upload record(s)", len(stale_ids))
    return len(stale_ids)


def activate_database_version(version: DatabaseVersion) -> DatabaseVersion:
    """Mark one database version active and deactivate all others."""
    with atomic():
        DatabaseVersion.objects.exclude(pk=version.pk).update(is_active=False)
        if not version.is_active:
            version.is_active = True
            version.save(update_fields=["is_active"])
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
