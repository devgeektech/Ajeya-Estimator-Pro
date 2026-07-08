"""Database rollback service.

Restores a previously imported DatabaseVersion as the active version. The
retention policy keeps the active version plus two previous versions
(docs/DATABASE_ARCHITECTURE.md - Retention Policy), so only retained versions
can be rolled back to.
"""

from __future__ import annotations

import logging

from django.db import transaction

from ai.context import clear_database_context_cache
from common.exceptions import BOQAIError

from ..models import DatabaseVersion

logger = logging.getLogger("boq_ai")


class DatabaseRollbackService:
    def __init__(self, target_version: DatabaseVersion):
        self.target_version = target_version

    def run(self) -> DatabaseVersion:
        if self.target_version.is_active:
            raise BOQAIError("That database version is already active.")

        with transaction.atomic():
            DatabaseVersion.objects.exclude(pk=self.target_version.pk).update(
                is_active=False
            )
            self.target_version.is_active = True
            self.target_version.save(update_fields=["is_active"])

        clear_database_context_cache()
        logger.info("Database rolled back to v%s", self.target_version.version_number)
        return self.target_version
