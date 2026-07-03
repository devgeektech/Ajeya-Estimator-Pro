"""Activity extraction (Phase 4, Sprint 9).

Identifies execution activities implied by a BOQ description (excavation,
installation, testing, etc.). Activities feed labour/transport/overheads in
later costing phases (docs/PRD.md - Activity Extraction).
"""
from __future__ import annotations

from ai.service import AIService

PROMPT = "activity_extraction.txt"

ALLOWED_ACTIVITIES = {
    "excavation", "trenching", "backfilling", "installation",
    "testing", "commissioning", "painting", "supports",
}


def extract_activities(description: str, service: AIService | None = None) -> list[str]:
    """Return a list of recognised activity names for a description."""
    service = service or AIService()
    data = service.run_json_prompt(PROMPT, description=description)
    activities = data.get("activities", []) if isinstance(data, dict) else []
    result: list[str] = []
    for activity in activities:
        if isinstance(activity, str) and activity.strip().lower() in ALLOWED_ACTIVITIES:
            result.append(activity.strip().lower())
    return result
