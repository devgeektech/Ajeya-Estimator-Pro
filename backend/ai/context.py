"""Compact database context for AI extraction prompts."""
from __future__ import annotations

import json

from apps.database_manager.models import DatabaseVersion, LabourMaster, RateMaster, TORLabour


def _unique(values, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def build_database_context(limit: int = 80) -> str:
    """Return active database vocabulary as JSON for extraction prompts."""
    version = DatabaseVersion.objects.filter(is_active=True).first()
    if version is None:
        return json.dumps(
            {
                "products": [],
                "categories": [],
                "subcategories": [],
                "makes": [],
                "activities": [],
            }
        )

    rates = RateMaster.objects.filter(database_version=version).order_by("product_code")
    products = [
        {
            "product_code": rate.product_code,
            "description": rate.description,
            "category": rate.category,
            "subcategory": rate.subcategory,
            "make": rate.make,
            "unit": rate.unit,
        }
        for rate in rates[:limit]
    ]
    activities = _unique(
        list(
            LabourMaster.objects.filter(database_version=version).values_list(
                "labour_name", flat=True
            )
        )
        + list(
            LabourMaster.objects.filter(database_version=version).values_list(
                "labour_code", flat=True
            )
        )
        + list(
            TORLabour.objects.filter(database_version=version).values_list(
                "labour_code", flat=True
            )
        ),
        limit,
    )
    payload = {
        "products": products,
        "categories": _unique(rates.values_list("category", flat=True), limit),
        "subcategories": _unique(rates.values_list("subcategory", flat=True), limit),
        "makes": _unique(rates.values_list("make", flat=True), limit),
        "activities": activities,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
