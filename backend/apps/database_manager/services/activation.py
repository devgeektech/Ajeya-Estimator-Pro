"""Ensure exactly one DatabaseVersion is active at a time."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from common.constants import DATABASE_UPLOADS_TO_RETAIN
from common.db import atomic

from ..models import MASTER_DATA_MODELS, DatabaseVersion

logger = logging.getLogger("boq_ai")


def purge_inactive_master_data(active: DatabaseVersion) -> int:
    """Remove PostgreSQL master rows for every version except the active one.

    ``DatabaseVersion`` records and stored workbooks are kept (until retention
    drops them) so users can still view upload history and download archived
    sheets. Chroma vectors for inactive versions are cleared here.
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


def _delete_version_workbook(version: DatabaseVersion) -> None:
    """Remove the workbook under ``media/database/`` for one upload record."""
    file_field = version.file
    if not file_field or not file_field.name:
        return
    relative = str(file_field.name).replace("\\", "/")
    try:
        if file_field.storage.exists(file_field.name):
            file_field.delete(save=False)
            logger.info(
                "Retention: deleted workbook %s for database v%s",
                relative,
                version.version_number,
            )
            return
    except Exception:
        logger.exception(
            "Retention: storage delete failed for database v%s (%s)",
            version.version_number,
            relative,
        )

    # Fallback: unlink under MEDIA_ROOT/database only (never outside).
    media_root = Path(settings.MEDIA_ROOT).resolve()
    candidate = (media_root / relative).resolve()
    database_root = (media_root / "database").resolve()
    try:
        if database_root not in candidate.parents and candidate.parent != database_root:
            logger.error(
                "Retention: refusing to delete path outside media/database: %s",
                candidate,
            )
            return
        if candidate.is_file():
            candidate.unlink()
            logger.info(
                "Retention: unlinked workbook %s for database v%s",
                candidate,
                version.version_number,
            )
    except OSError:
        logger.warning(
            "Retention: could not unlink workbook for database v%s (%s)",
            version.version_number,
            candidate,
        )


def enforce_version_retention() -> int:
    """Keep only the newest ``DATABASE_UPLOADS_TO_RETAIN`` uploads.

    Called after a **successful** import (activate + purge). When the 11th
    version succeeds, the oldest (1st) ``DatabaseVersion`` row and its
    ``media/database/`` workbook are removed. PostgreSQL master rows for that
    oldest version were already purged when it stopped being active.
    """
    versions = list(DatabaseVersion.objects.order_by("-version_number", "-id"))
    if len(versions) <= DATABASE_UPLOADS_TO_RETAIN:
        return 0

    stale = versions[DATABASE_UPLOADS_TO_RETAIN:]
    stale_ids = [version.pk for version in stale]

    for version in stale:
        _delete_version_workbook(version)

    DatabaseVersion.objects.filter(pk__in=stale_ids).delete()
    logger.info(
        "Retention: removed %s old database upload(s); kept newest %s",
        len(stale_ids),
        DATABASE_UPLOADS_TO_RETAIN,
    )
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
