"""Database rollback service.

Restores a previously imported DatabaseVersion as the active version. The
retention policy keeps the active version plus two previous versions
(docs/DATABASE.md - retention policy), so only retained versions
can be rolled back to.
"""

from __future__ import annotations

import logging

from django.db import transaction

from common.exceptions import BOQAIError

from ..models import DatabaseVersion
from .activation import activate_database_version

logger = logging.getLogger("boq_ai")


class DatabaseRollbackService:
    def __init__(self, target_version: DatabaseVersion):
        self.target_version = target_version

    def run(self) -> DatabaseVersion:
        if self.target_version.is_active:
            raise BOQAIError("That database version is already active.")

        with transaction.atomic():
            activate_database_version(self.target_version)

        logger.info("Database rolled back to v%s", self.target_version.version_number)
        return self.target_version
