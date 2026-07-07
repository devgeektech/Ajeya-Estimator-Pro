"""Database import workflow.

Validate -> Backup -> Import -> Activate -> Embeddings
(docs/PROJECT_STRUCTURE.md - Import Rules). Thin orchestration over
DatabaseImportService for synchronous database uploads.
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from apps.database_manager.services.importer import DatabaseImportService

logger = logging.getLogger("boq_ai")


def import_database(file_path: str, uploaded_by_id: int, source_filename: str | None = None, version_name: str = "", stored_name: str = ""):
    """Import a master workbook into a new, activated DatabaseVersion."""
    User = get_user_model()
    uploaded_by = User.objects.filter(pk=uploaded_by_id).first()
    service = DatabaseImportService(
        file_path=file_path,
        uploaded_by=uploaded_by,
        source_filename=source_filename,
        version_name=version_name,
        stored_name=stored_name,
    )
    version = service.run()
    return version.pk
