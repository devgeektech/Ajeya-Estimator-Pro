"""Celery task: process a BOQ run asynchronously."""
import logging

from celery import shared_task

from apps.boq.models import BOQRun
from workflows.boq_processing import process_boq_run

logger = logging.getLogger("boq_ai")


@shared_task(name="process_boq_task")
def process_boq_task(boq_run_id: int):
    if not BOQRun.objects.filter(pk=boq_run_id).exists():
        logger.warning("Skipping BOQ processing task: run %s no longer exists", boq_run_id)
        return None
    return process_boq_run(boq_run_id)
