"""Product extraction (Phase 4, Sprint 8).

Extracts structured product attributes (product / size / material / make) from a
BOQ description using AIService. AI is used only for understanding/extraction
(docs/AGENTS.md - AI Rules); pricing and vendor selection happen elsewhere.
"""
from __future__ import annotations

from ai.service import AIService

PROMPT = "product_extraction.txt"
FIELDS = ("product", "size", "material", "make")


def extract_product(description: str, service: AIService | None = None) -> dict:
    """Return {product, size, material, make} for a description."""
    service = service or AIService()
    data = service.run_json_prompt(PROMPT, description=description)
    if not isinstance(data, dict):
        return {field: None for field in FIELDS}
    return {field: data.get(field) for field in FIELDS}
