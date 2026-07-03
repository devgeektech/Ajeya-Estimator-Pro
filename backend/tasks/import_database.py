"""Celery task: import a master database workbook (background).

Long-running imports must not block views (docs/AGENTS.md - Background Jobs).
Runs eagerly in local settings (CELERY_TASK_ALWAYS_EAGER).
"""
from celery import shared_task

from workflows.database_import import import_database


@shared_task(name="import_database_task")
def import_database_task(file_path: str, uploaded_by_id: int, source_filename: str = "", version_name: str = "", stored_name: str = ""):
    return import_database(file_path, uploaded_by_id, source_filename or None, version_name, stored_name)
