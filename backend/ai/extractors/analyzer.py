"""AI analysis coordinator (Phase 4, Sprints 8-9).

Runs product + activity extraction for every item in a BOQ run and persists the
results. Errors on a single item are logged and skipped so one bad row never
fails the whole run (docs/AGENTS.md - Error Handling). Callers must ensure AI is
enabled (AIService.is_enabled()) before invoking analyze_run.
"""
from __future__ import annotations

import json
import logging

from common.exceptions import AIServiceError

from ai.context import build_database_context
from ai.service import AIService
from ai.extractors.activity_extractor import extract_activities
from ai.extractors.product_extractor import extract_product
from apps.matching.models import ActivityMatch

logger = logging.getLogger("boq_ai")
row_logger = logging.getLogger("boq_ai.ai_rows")


def _log_row_extraction(item, product_data: dict, activities: list[str]) -> None:
    """Write one structured AI extraction log line for a BOQ item."""
    ai_output = {
        "product_extraction": product_data,
        "activities": activities,
    }
    payload = {
        "event": "ai_row_extraction",
        "boq_id": item.boq_run.boq_id,
        "boq_run_id": item.boq_run_id,
        "boq_item_id": item.pk,
        "excel_row_number": item.row_number,
        "description": item.description,
        "fetched_row_json": item.row_json,
        "ai_output_json": ai_output,
        "row_json": item.row_json,
        "product_extraction": product_data,
        "activities": activities,
    }
    row_logger.info(json.dumps(payload, ensure_ascii=False, default=str))


def _log_row_failure(item, error: Exception) -> None:
    """Write one structured AI extraction failure log line for a BOQ item."""
    payload = {
        "event": "ai_row_extraction_failed",
        "boq_id": item.boq_run.boq_id,
        "boq_run_id": item.boq_run_id,
        "boq_item_id": item.pk,
        "excel_row_number": item.row_number,
        "description": item.description,
        "fetched_row_json": item.row_json,
        "row_json": item.row_json,
        "error": str(error),
    }
    row_logger.error(json.dumps(payload, ensure_ascii=False, default=str))


def analyze_run(run) -> int:
    """Extract products + activities for each item in a run.

    Returns the number of items successfully analyzed.
    """
    service = AIService()
    database_context = build_database_context()
    analyzed = 0

    for item in run.items.all():
        try:
            product_data = extract_product(
                item.description,
                service=service,
                row_json=item.row_json,
                database_context=database_context,
            )
            item.ai_extraction = product_data
            item.save(update_fields=["ai_extraction"])

            activities = extract_activities(
                item.description,
                service=service,
                row_json=item.row_json,
                database_context=database_context,
            )
            # Replace prior activity matches for idempotent reprocessing.
            item.activity_matches.all().delete()
            ActivityMatch.objects.bulk_create(
                [ActivityMatch(boq_item=item, activity_name=name) for name in activities]
            )
            _log_row_extraction(item, product_data, activities)
            analyzed += 1
        except AIServiceError as exc:
            _log_row_failure(item, exc)
            logger.exception("AI analysis failed for item %s; skipping", item.pk)
            continue

    logger.info("Run %s: AI analysis complete (%s/%s items)", run.pk, analyzed, run.items.count())
    return analyzed
