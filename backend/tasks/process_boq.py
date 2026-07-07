"""Celery task: process a BOQ run asynchronously.

Wraps workflows.boq_processing.process_boq_run. Views must never block
(docs/AGENTS.md - Background Jobs).
"""
from celery import shared_task

from workflows.boq_processing import process_boq_run


@shared_task(name="process_boq_task")
def process_boq_task(boq_run_id: int):
    return process_boq_run(boq_run_id)
