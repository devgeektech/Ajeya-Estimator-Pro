"""Run master database import synchronously (single global lock)."""
from __future__ import annotations

import logging

from apps.audit.services import record
from apps.database_manager.services.database_import_progress import (
    is_import_busy,
    mark_import_failed,
    mark_import_succeeded,
    try_begin_import,
    update_import_phase,
)
from apps.database_manager.services.importer import DatabaseImportService
from apps.notifications.services import notify
from common.exceptions import BOQAIError, ImportError_

logger = logging.getLogger("boq_ai")


def run_database_import(
    *,
    file_path: str,
    uploaded_by,
    source_filename: str,
    version_name: str,
    stored_name: str,
):
    """
    Acquire the global lock and import in this process (HTTP request).

    Returns the activated DatabaseVersion on success.
    Raises ImportError_ / BOQAIError on failure; previous active DB unchanged.
    """
    if is_import_busy():
        raise ImportError_(
            "A database import is already in progress. Wait until it finishes."
        )

    email = getattr(uploaded_by, "email", "") or ""
    user_id = getattr(uploaded_by, "pk", None)
    if not try_begin_import(
        uploaded_by_id=user_id,
        uploaded_by_email=email,
        filename=source_filename,
    ):
        raise ImportError_(
            "A database import is already in progress. Wait until it finishes."
        )

    try:
        update_import_phase("importing", "Importing workbook sheets…")
        version = DatabaseImportService(
            file_path=file_path,
            uploaded_by=uploaded_by,
            source_filename=source_filename,
            version_name=version_name,
            stored_name=stored_name,
            progress_callback=update_import_phase,
        ).run()
        mark_import_succeeded(
            version_number=version.version_number,
            message=(
                f"Database v{version.version_number} is active. "
                "Embeddings completed and previous master data was purged."
            ),
        )
        if uploaded_by is not None:
            record(uploaded_by, "database_import", "Workbook", source_filename)
            notify(
                uploaded_by,
                "Database activated",
                (
                    f"'{version_name or source_filename}' was imported and is now "
                    "the active database."
                ),
            )
        return version
    except BOQAIError as exc:
        logger.warning("Database import failed: %s", exc)
        mark_import_failed(str(exc))
        raise
    except Exception as exc:
        logger.exception("Database import crashed")
        mark_import_failed(f"Database import failed: {exc}")
        raise ImportError_(f"Database import failed: {exc}") from exc
