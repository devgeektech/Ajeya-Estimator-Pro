"""AI analysis coordinator (Phase 4, Sprints 8-9).

Runs product + activity extraction for every item in a BOQ run and persists the
results. Errors on a single item are logged and skipped so one bad row never
fails the whole run (docs/AGENTS.md - Error Handling). Callers must ensure AI is
enabled (AIService.is_enabled()) before invoking analyze_run.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from django.conf import settings

from common.exceptions import AIServiceError

from ai.context import build_database_context
from ai.service import AIService
from ai.extractors.row_extractor import extract_boq_rows
from apps.matching.models import ActivityMatch

logger = logging.getLogger("boq_ai")
row_logger = logging.getLogger("boq_ai.ai_rows")


def _json_safe(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _compact_source_row_payload(payload: dict) -> dict:
    """Keep row context for AI without repeating the same source fields."""
    compact_rows = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in payload.get("rows", []):
        if not isinstance(row, dict):
            continue
        compact_row = {
            "excel_row_number": row.get("excel_row_number"),
            "serial_number": row.get("serial_number"),
            "description": row.get("description"),
            "unit": row.get("unit"),
            "quantity": _json_safe(row.get("quantity")),
        }
        if isinstance(row.get("canonical"), dict):
            compact_row["canonical"] = _json_safe(row["canonical"])
        key = tuple(
            str(compact_row.get(field) or "").strip().casefold()
            for field in (
                "excel_row_number",
                "serial_number",
                "description",
                "unit",
                "quantity",
            )
        )
        if key in seen:
            continue
        seen.add(key)
        compact_rows.append(compact_row)

    return {
        "schema": payload.get("schema") or "boq_row_group_v1",
        "primary_excel_row_number": payload.get("primary_excel_row_number"),
        "target_excel_row": payload.get("target_excel_row")
        or payload.get("primary_excel_row_number"),
        "excel_row_numbers": payload.get("excel_row_numbers")
        or [
            row.get("excel_row_number")
            for row in compact_rows
            if row.get("excel_row_number")
        ],
        "serial_number": payload.get("serial_number"),
        "description": payload.get("description") or _joined_descriptions(compact_rows),
        "unit": payload.get("unit") or _first_row_value(compact_rows, "unit"),
        "quantity": _json_safe(
            payload.get("quantity")
            if payload.get("quantity") not in (None, "")
            else _first_row_value(compact_rows, "quantity")
        ),
        "rows": compact_rows,
    }


def _joined_descriptions(rows: list[dict]) -> str:
    descriptions = [
        str(row.get("description") or "").strip()
        for row in rows
        if str(row.get("description") or "").strip()
    ]
    return "\n".join(descriptions)


def _first_row_value(rows: list[dict], key: str):
    for row in rows:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _source_row_payload(item) -> dict:
    """Return a traversable grouped-row payload for prompts and logs."""
    row_json = item.row_json
    if isinstance(row_json, str):
        try:
            row_json = json.loads(row_json)
        except json.JSONDecodeError:
            row_json = None
    if isinstance(row_json, dict) and isinstance(row_json.get("rows"), list):
        return _compact_source_row_payload(row_json)

    original = item.original_data if isinstance(item.original_data, dict) else {}
    description = original.get("description") or item.description
    unit = original.get("unit") or item.unit
    quantity = original.get("quantity")
    if quantity in (None, ""):
        # No stated quantity (e.g. a section/heading row): send null, not 0, so
        # the model does not read it as an actual quantity of zero.
        quantity = item.quantity if item.quantity else None

    row = {
        "unit": unit,
        "quantity": _json_safe(quantity),
        "description": description,
        "serial_number": original.get("s_no"),
        "excel_row_number": item.row_number,
    }
    return {
        "schema": "boq_row_group_v1",
        "excel_row_numbers": [item.row_number],
        "primary_excel_row_number": item.row_number,
        "target_excel_row": item.target_excel_row or item.row_number,
        "serial_number": original.get("s_no"),
        "description": description,
        "unit": unit,
        "quantity": _json_safe(quantity),
        "rows": [row],
    }


def _compact_products(products) -> list[dict]:
    """Keep only fields the AI actually returned so logs are readable."""
    compact: list[dict] = []
    for product in products if isinstance(products, list) else []:
        if not isinstance(product, dict):
            continue
        entry = {
            key: value for key, value in product.items() if value not in (None, "")
        }
        if entry:
            compact.append(entry)
    return compact


def _compact_extraction(extraction: dict) -> dict:
    """Drop null product fields so the log shows what was fetched, not blanks."""
    extraction = extraction if isinstance(extraction, dict) else {}
    return {
        "database_products": _compact_products(extraction.get("database_products", [])),
        "missing_products": _compact_products(extraction.get("missing_products", [])),
        "database_activities": extraction.get("database_activities")
        or extraction.get("activities", [])
        or [],
        "missing_activities": extraction.get("missing_activities", []) or [],
        "activities": extraction.get("database_activities")
        or extraction.get("activities", [])
        or [],
    }


def _log_source_row(source_row: dict) -> dict:
    """Readable source row for logs without the duplicated canonical scaffolding."""
    source_row = source_row if isinstance(source_row, dict) else {}
    rows = [
        {
            "excel_row_number": row.get("excel_row_number"),
            "serial_number": row.get("serial_number"),
            "description": row.get("description"),
            "unit": row.get("unit"),
            "quantity": row.get("quantity"),
        }
        for row in source_row.get("rows", [])
        if isinstance(row, dict)
    ]
    return {
        "serial_number": source_row.get("serial_number"),
        "excel_row_numbers": source_row.get("excel_row_numbers"),
        "description": source_row.get("description"),
        "unit": source_row.get("unit"),
        "quantity": source_row.get("quantity"),
        "rows": rows,
    }


def _log_row_extraction(item, source_row: dict, extraction: dict) -> None:
    """Write one readable AI extraction log line for a BOQ item.

    The line surfaces the analyzed description, the serial number, and only the
    non-null product fields the AI returned so a reviewer can see exactly what
    was fetched from the BOQ row.
    """
    compact = _compact_extraction(extraction)
    payload = {
        "event": "ai_row_extraction",
        "boq_id": item.boq_run.boq_id,
        "boq_run_id": item.boq_run_id,
        "boq_item_id": item.pk,
        "excel_row_number": item.row_number,
        "serial_number": source_row.get("serial_number"),
        "description": source_row.get("description"),
        "products": compact["database_products"] + compact["missing_products"],
        "database_activities": compact["database_activities"],
        "missing_activities": compact["missing_activities"],
        "activities": compact["activities"],
        "source_row": _log_source_row(source_row),
        "extraction": compact,
    }
    row_logger.info(json.dumps(payload, ensure_ascii=False, default=str))


def _log_row_failure(item, source_row: dict, error: Exception) -> None:
    """Write one readable AI extraction failure log line for a BOQ item."""
    payload = {
        "event": "ai_row_extraction_failed",
        "boq_id": item.boq_run.boq_id,
        "boq_run_id": item.boq_run_id,
        "boq_item_id": item.pk,
        "excel_row_number": item.row_number,
        "serial_number": source_row.get("serial_number"),
        "description": source_row.get("description"),
        "source_row": _log_source_row(source_row),
        "error": str(error),
    }
    row_logger.error(json.dumps(payload, ensure_ascii=False, default=str))


def _chunks(items: list, size: int):
    for index in range(0, len(items), max(size, 1)):
        yield items[index : index + max(size, 1)]


def _extract_batch_with_fallback(
    *,
    batch_payload: list[dict],
    service: AIService,
    database_context: str,
    run_id: int,
) -> tuple[dict, dict[str, AIServiceError]]:
    """Retry failed AI batches in smaller chunks before dropping rows."""
    try:
        return (
            extract_boq_rows(
                batch_payload,
                service=service,
                database_context=database_context,
            ),
            {},
        )
    except AIServiceError as exc:
        if len(batch_payload) <= 1:
            row_id = str(batch_payload[0].get("row_id"))
            return {}, {row_id: exc}

        midpoint = len(batch_payload) // 2
        logger.warning(
            "AI analysis failed for batch in run %s; retrying as %s and %s rows",
            run_id,
            midpoint,
            len(batch_payload) - midpoint,
        )
        left_results, left_failures = _extract_batch_with_fallback(
            batch_payload=batch_payload[:midpoint],
            service=service,
            database_context=database_context,
            run_id=run_id,
        )
        right_results, right_failures = _extract_batch_with_fallback(
            batch_payload=batch_payload[midpoint:],
            service=service,
            database_context=database_context,
            run_id=run_id,
        )
        return {**left_results, **right_results}, {**left_failures, **right_failures}


def _persist_extraction(item, source_row: dict, extraction: dict) -> None:
    database_activities = extraction.get("database_activities")
    if not isinstance(database_activities, list):
        database_activities = extraction.get("activities", [])
    missing_activities = extraction.get("missing_activities", [])
    item.ai_extraction = {
        "schema": "boq_product_extraction_v1",
        "database_products": extraction.get("database_products", []),
        "missing_products": extraction.get("missing_products", []),
        "database_activities": database_activities,
        "missing_activities": missing_activities,
        "activities": database_activities,
    }
    item.save(update_fields=["ai_extraction"])

    # Replace prior activity matches for idempotent reprocessing.
    item.activity_matches.all().delete()
    ActivityMatch.objects.bulk_create(
        [
            ActivityMatch(boq_item=item, activity_name=name)
            for name in database_activities
        ]
    )
    _log_row_extraction(item, source_row, extraction)


def analyze_run(run) -> int:
    """Extract products + activities for each item in a run.

    Returns the number of items successfully analyzed.
    """
    service = AIService()
    database_context = build_database_context()
    batch_size = getattr(settings, "AI_ROW_EXTRACTION_BATCH_SIZE", 10)
    analyzed = 0
    items = list(run.items.all())

    for batch in _chunks(items, batch_size):
        source_rows = {item.pk: _source_row_payload(item) for item in batch}
        batch_payload = [
            {
                "row_id": str(item.pk),
                "description": item.description,
                "row_json": source_rows[item.pk],
            }
            for item in batch
        ]
        extractions, failures = _extract_batch_with_fallback(
            batch_payload=batch_payload,
            service=service,
            database_context=database_context,
            run_id=run.pk,
        )
        if failures:
            for item in batch:
                failure = failures.get(str(item.pk))
                if failure is not None:
                    _log_row_failure(item, source_rows[item.pk], failure)
            logger.error(
                "AI analysis failed for %s row(s) in run %s; skipped failed rows",
                len(failures),
                run.pk,
            )

        for item in batch:
            if str(item.pk) in failures:
                continue
            extraction = extractions.get(str(item.pk))
            if not extraction:
                extraction = {
                    "schema": "boq_ai_extraction_v1",
                    "database_products": [],
                    "missing_products": [],
                    "database_activities": [],
                    "missing_activities": [],
                    "activities": [],
                }
            _persist_extraction(item, source_rows[item.pk], extraction)
            analyzed += 1

    logger.info(
        "Run %s: AI analysis complete (%s/%s items)",
        run.pk,
        analyzed,
        run.items.count(),
    )
    return analyzed
