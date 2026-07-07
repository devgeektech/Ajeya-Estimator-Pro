"""Product extraction (Phase 4, Sprint 8).

Extracts structured product attributes (product / size / material / make) from a
BOQ description using AIService. AI is used only for understanding/extraction
(docs/AGENTS.md - AI Rules); pricing and rate selection happen in services.
"""
from __future__ import annotations

import json

from ai.service import AIService

PROMPT = "product_extraction.txt"
FIELDS = ("product", "size", "material", "make")


def _empty_result() -> dict:
    return {field: None for field in FIELDS} | {"products": []}


def extract_product(
    description: str,
    service: AIService | None = None,
    *,
    row_json: dict | None = None,
    database_context: str = "{}",
) -> dict:
    """Return structured product extraction for a grouped BOQ row."""
    service = service or AIService()
    payload = row_json or {"description": description, "rows": [{"description": description}]}
    data = service.run_json_prompt(
        PROMPT,
        description=description,
        row_json=json.dumps(payload, ensure_ascii=False, default=str),
        database_context=database_context,
    )
    if not isinstance(data, dict):
        return _empty_result()
    products = data.get("products")
    if not isinstance(products, list):
        products = []
    primary = products[0] if products and isinstance(products[0], dict) else data
    result = {field: primary.get(field) for field in FIELDS}
    result["products"] = [
        {field: product.get(field) for field in FIELDS}
        | {
            "category": product.get("category"),
            "subcategory": product.get("subcategory"),
            "database_hint": product.get("database_hint"),
        }
        for product in products
        if isinstance(product, dict)
    ]
    return result
