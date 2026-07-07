"""Activity extraction (Phase 4, Sprint 9).

Identifies execution activities implied by a BOQ description. Activities feed
labour, transport, and overhead costing (docs/PRD.md - Activity Extraction).
"""
from __future__ import annotations

import json

from ai.service import AIService

PROMPT = "activity_extraction.txt"

ALLOWED_ACTIVITIES = {
    "excavation", "trenching", "backfilling", "installation",
    "testing", "commissioning", "painting", "supports",
}


def _allowed_from_context(database_context: str) -> set[str]:
    try:
        payload = json.loads(database_context or "{}")
    except json.JSONDecodeError:
        payload = {}
    activities = payload.get("activities") if isinstance(payload, dict) else None
    if not activities:
        return ALLOWED_ACTIVITIES
    return {str(activity).strip().lower() for activity in activities if str(activity).strip()}


def extract_activities(
    description: str,
    service: AIService | None = None,
    *,
    row_json: dict | None = None,
    database_context: str = "{}",
) -> list[str]:
    """Return recognised activity names for a grouped BOQ row."""
    service = service or AIService()
    payload = row_json or {"description": description, "rows": [{"description": description}]}
    data = service.run_json_prompt(
        PROMPT,
        description=description,
        row_json=json.dumps(payload, ensure_ascii=False, default=str),
        database_context=database_context,
    )
    activities = data.get("activities", []) if isinstance(data, dict) else []
    allowed = _allowed_from_context(database_context)
    result: list[str] = []
    for activity in activities:
        if isinstance(activity, str) and activity.strip().lower() in allowed:
            result.append(activity.strip().lower())
    return result
