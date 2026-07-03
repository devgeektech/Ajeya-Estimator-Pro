"""Celery task: process a BOQ run asynchronously (scaffold).

Wraps workflows.boq_processing.process_boq_run. Views must never block
(docs/AGENTS.md - Background Jobs).
"""
from celery import shared_task


@shared_task(name="process_boq_task")
def process_boq_task(boq_run_id: int):
    from workflows.boq_processing import process_boq_run

    return process_boq_run(boq_run_id)
