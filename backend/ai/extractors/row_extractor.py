"""AI extraction for grouped BOQ rows.

The model reads grouped row context and returns database-present product
candidates, missing product candidates, and activities. Pricing and rate/labour
retrieval remain in business services.
"""

from __future__ import annotations

import json

from ai.service import AIService

PROMPT = "boq_row_extraction.txt"
BATCH_PROMPT = "boq_row_batch_extraction.txt"
PRODUCT_FIELDS = (
    "product_name",
    "category",
    "sub_category",
    "class",
    "size_mm",
    "make",
    "capacity",
    "unit",
    "height",
    "working_pressure",
    "test_pressure",
    "temperature",
    "throw",
    "k_factor",
    "head",
    "supplier",
    "product_quantity",
    "product_unit",
    "quantity_basis",
    "quantity_source",
)
FIELD_ALIASES = {
    "product": "product_name",
    "name": "product_name",
    "item": "product_name",
    "sub category": "sub_category",
    "size": "size_mm",
    "size.mm": "size_mm",
    "sime.mm": "size_mm",
    "working pressure": "working_pressure",
    "test pressure": "test_pressure",
    "temp": "temperature",
    "thorw": "throw",
    "kfactor": "k_factor",
    "quantity": "product_quantity",
    "qty": "product_quantity",
    "product qty": "product_quantity",
    "product unit": "product_unit",
    "qty_basis": "quantity_basis",
    "basis": "quantity_basis",
}
VALID_QUANTITY_BASIS = {"per_boq_unit", "total_for_boq_row", "unknown"}
FALLBACK_ACTIVITIES = {
    "excavation",
    "trenching",
    "backfilling",
    "installation",
    "testing",
    "commissioning",
    "painting",
    "supports",
}


def _empty_result() -> dict:
    return {
        "schema": "boq_ai_extraction_v1",
        "database_products": [],
        "missing_products": [],
        "database_activities": [],
        "missing_activities": [],
        "activities": [],
    }


def _value(product: dict, field: str):
    if field in product:
        return product.get(field)
    for source, target in FIELD_ALIASES.items():
        if target == field and source in product:
            return product.get(source)
    return None


def _clean_product(product: dict) -> dict:
    cleaned = {}
    for field in PRODUCT_FIELDS:
        value = _value(product, field)
        if isinstance(value, str):
            value = value.strip() or None
        cleaned[field] = value
    basis = str(cleaned.get("quantity_basis") or "").strip()
    if basis not in VALID_QUANTITY_BASIS:
        basis = "unknown"
    cleaned["quantity_basis"] = basis
    if cleaned.get("product_quantity") in (None, ""):
        cleaned["product_quantity"] = "1"
    if not cleaned.get("quantity_source"):
        cleaned["quantity_source"] = "ai" if basis != "unknown" else "unknown"
    return cleaned


def _product_key(product: dict) -> tuple[str, ...]:
    return tuple(
        str(product.get(field) or "").strip().casefold() for field in PRODUCT_FIELDS
    )


def _clean_products(products) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for product in products if isinstance(products, list) else []:
        if not isinstance(product, dict) or not any(
            _value(product, field) for field in PRODUCT_FIELDS
        ):
            continue
        cleaned = _clean_product(product)
        key = _product_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _allowed_activities(database_context: str) -> set[str]:
    try:
        payload = json.loads(database_context or "{}")
    except json.JSONDecodeError:
        payload = {}
    activities = payload.get("activities") if isinstance(payload, dict) else None
    if not activities:
        return FALLBACK_ACTIVITIES
    return {
        str(activity).strip().lower()
        for activity in activities
        if str(activity).strip()
    }


def _split_activities(activities, database_context: str) -> tuple[list[str], list[str]]:
    """Split extracted activities into database vocabulary vs unknown terms."""
    allowed = _allowed_activities(database_context)
    database_activities: list[str] = []
    missing_activities: list[str] = []
    for activity in activities if isinstance(activities, list) else []:
        text = str(activity).strip().lower()
        if not text:
            continue
        if text in allowed:
            if text not in database_activities:
                database_activities.append(text)
        elif text not in missing_activities:
            missing_activities.append(text)
    return database_activities, missing_activities


def _clean_activities(activities, database_context: str) -> list[str]:
    database_activities, _ = _split_activities(activities, database_context)
    return database_activities


def extract_boq_row(
    description: str,
    service: AIService | None = None,
    *,
    row_json: dict | None = None,
    database_context: str = "{}",
) -> dict:
    """Return product candidates and activities for a grouped BOQ row."""
    service = service or AIService()
    payload = row_json or {
        "description": description,
        "rows": [{"description": description}],
    }
    data = service.run_json_prompt(
        PROMPT,
        description=description,
        row_json=json.dumps(payload, ensure_ascii=False, default=str),
        database_context=database_context,
    )
    if not isinstance(data, dict):
        return _empty_result()
    return _clean_extraction(data, database_context)


def _clean_extraction(data: dict, database_context: str) -> dict:
    database_products = data.get("database_products")
    missing_products = data.get("missing_products")
    products = data.get("products")

    if not isinstance(database_products, list):
        database_products = []
    if not isinstance(missing_products, list):
        missing_products = []
    if not database_products and not missing_products and isinstance(products, list):
        database_products = products
    if (
        not database_products
        and not missing_products
        and any(_value(data, field) for field in PRODUCT_FIELDS)
    ):
        database_products = [data]
    database_activities, missing_activities = _split_activities(
        data.get("activities"), database_context
    )
    return {
        "schema": "boq_ai_extraction_v1",
        "database_products": _clean_products(database_products),
        "missing_products": _clean_products(missing_products),
        "database_activities": database_activities,
        "missing_activities": missing_activities,
        "activities": database_activities,
    }


def extract_boq_rows(
    rows: list[dict],
    service: AIService | None = None,
    *,
    database_context: str = "{}",
) -> dict[str, dict]:
    """Return row_id -> extraction for a batch of grouped BOQ rows."""
    service = service or AIService()
    if not rows:
        return {}

    payload = [
        {
            "row_id": str(row.get("row_id")),
            "description": row.get("description") or "",
            "row_json": row.get("row_json") or {},
        }
        for row in rows
        if row.get("row_id") is not None
    ]
    data = service.run_json_prompt(
        BATCH_PROMPT,
        rows_json=json.dumps(payload, ensure_ascii=False, default=str),
        database_context=database_context,
    )
    if not isinstance(data, dict):
        return {row["row_id"]: _empty_result() for row in payload}

    response_rows = data.get("rows")
    if not isinstance(response_rows, list):
        response_rows = []

    results: dict[str, dict] = {row["row_id"]: _empty_result() for row in payload}
    for row in response_rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("row_id") or "").strip()
        if not row_id:
            continue
        extraction = row.get("extraction")
        if not isinstance(extraction, dict):
            extraction = row
        results[row_id] = _clean_extraction(extraction, database_context)
    return results
