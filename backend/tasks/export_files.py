"""Celery task: generate export workbooks."""
from celery import shared_task

from apps.accounts.models import User
from apps.boq.models import BOQRun
from apps.exports.services.export_service import ExportService


@shared_task(name="export_files_task")
def export_files_task(boq_run_id: int, exported_by_id: int):
    run = BOQRun.objects.select_related("boq", "boq__user").get(pk=boq_run_id)
    user = User.objects.filter(pk=exported_by_id).first()
    return ExportService().export_run(run, user=user).pk
