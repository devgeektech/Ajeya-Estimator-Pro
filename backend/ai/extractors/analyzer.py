"""AI analysis coordinator (Phase 4, Sprints 8-9).

Runs product + activity extraction for every item in a BOQ run and persists the
results. Errors on a single item are logged and skipped so one bad row never
fails the whole run (docs/AGENTS.md - Error Handling). Callers must ensure AI is
enabled (AIService.is_enabled()) before invoking analyze_run.
"""
from __future__ import annotations

import logging

from common.exceptions import AIServiceError

from ai.service import AIService
from ai.extractors.activity_extractor import extract_activities
from ai.extractors.product_extractor import extract_product
from apps.matching.models import ActivityMatch

logger = logging.getLogger("boq_ai")


def analyze_run(run) -> int:
    """Extract products + activities for each item in a run.

    Returns the number of items successfully analyzed.
    """
    service = AIService()
    analyzed = 0

    for item in run.items.all():
        try:
            item.ai_extraction = extract_product(item.description, service=service)
            item.save(update_fields=["ai_extraction"])

            activities = extract_activities(item.description, service=service)
            # Replace prior activity matches for idempotent reprocessing.
            item.activity_matches.all().delete()
            ActivityMatch.objects.bulk_create(
                [ActivityMatch(boq_item=item, activity_name=name) for name in activities]
            )
            analyzed += 1
        except AIServiceError:
            logger.exception("AI analysis failed for item %s; skipping", item.pk)
            continue

    logger.info("Run %s: AI analysis complete (%s/%s items)", run.pk, analyzed, run.items.count())
    return analyzed
