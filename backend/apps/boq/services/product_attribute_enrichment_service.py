"""Enrich extracted products with Rate_Master attribute schemas and confidence."""
from __future__ import annotations

import logging
from typing import Any

from apps.boq.services.product_matching_service import ProductMatchingService
from apps.database_manager.models import Rate_Master
from utils.attribute_parser import normalize_attribute_key, normalize_attribute_value, parse_attributes

logger = logging.getLogger("boq_ai")


def humanize_attribute_key(key: str) -> str:
    text = str(key or "").strip().replace("_", " ")
    if not text:
        return ""
    if text.upper() == "IS" or text.lower() == "is":
        return "IS Standard"
    return text[:1].upper() + text[1:]


def confidence_band(score: float) -> str:
    """Map attribute confidence to UI color band."""
    if score > 90:
        return "green"
    if score > 80:
        return "yellow"
    if score > 70:
        return "orange"
    return "red"


def compute_attribute_confidence(
    schema_keys: list[str],
    attributes: dict[str, Any],
) -> float:
    """Score 0–100 from how many schema attributes have a filled value."""
    keys = [str(key) for key in schema_keys if str(key).strip()]
    if not keys:
        return 0.0
    attrs = attributes or {}
    found = 0
    for key in keys:
        value = attrs.get(key)
        if value is None:
            continue
        if str(value).strip():
            found += 1
    return round(100.0 * found / len(keys), 2)


def merge_attributes_onto_schema(
    *,
    schema_keys: list[str],
    extracted_attrs: dict[str, Any],
) -> dict[str, str]:
    """Fill DB schema keys with matching extracted values; keep unmatched extras."""
    extracted = {
        normalize_attribute_key(str(key)): str(value).strip()
        for key, value in (extracted_attrs or {}).items()
        if value is not None and str(value).strip()
    }
    schema_set = set(schema_keys)
    merged: dict[str, str] = {}
    for key in schema_keys:
        if key in extracted:
            merged[key] = extracted[key]
    for key, value in extracted.items():
        if key not in schema_set:
            merged[key] = value
    return merged


class ProductAttributeEnrichmentService:
    """Search Rate_Master, apply DB attribute keys, score fill confidence."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id
        self._matcher = ProductMatchingService(database_version_id)

    def enrich_product(self, product: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(product)
        extracted_attrs = dict(enriched.get("attributes") or {})
        match = self._matcher.match_product(enriched)
        best = self._best_candidate(match)
        if best is None:
            schema_keys = sorted(normalize_attribute_key(str(k)) for k in extracted_attrs)
            schema_keys = [key for key in schema_keys if key]
            filled = {
                key: normalize_attribute_value(value)
                for key, value in extracted_attrs.items()
                if value is not None and str(value).strip()
            }
            confidence = compute_attribute_confidence(schema_keys, filled) if schema_keys else 0.0
            enriched["attributes"] = filled
            enriched["attribute_schema"] = schema_keys
            enriched["attribute_confidence"] = confidence
            enriched["attribute_source"] = "extracted"
            enriched["db_product_id"] = None
            return enriched

        rate = Rate_Master.objects.filter(
            pk=best["rate_master_id"],
            database_version_id=self.database_version_id,
        ).first()
        db_attrs = parse_attributes(rate.Attribute) if rate else {}
        schema_keys = list(db_attrs.keys()) if db_attrs else sorted(
            normalize_attribute_key(str(k)) for k in extracted_attrs if str(k).strip()
        )
        filled = merge_attributes_onto_schema(
            schema_keys=schema_keys,
            extracted_attrs=extracted_attrs,
        )
        # Confidence counts only schema keys that received an extracted value.
        schema_filled = {key: filled[key] for key in schema_keys if key in filled}
        confidence = compute_attribute_confidence(schema_keys, schema_filled)

        enriched["attributes"] = filled
        enriched["attribute_schema"] = schema_keys
        enriched["attribute_confidence"] = confidence
        enriched["attribute_source"] = "database" if db_attrs else "extracted"
        enriched["db_product_id"] = best.get("rate_master_id")
        enriched["db_product_make"] = best.get("make")
        enriched["db_match_confidence"] = best.get("confidence")
        return enriched

    def enrich_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched_rows: list[dict[str, Any]] = []
        for row in rows:
            if row.get("skip_matching"):
                enriched_rows.append(row)
                continue
            products = [
                self.enrich_product(product)
                for product in (row.get("products") or [])
            ]
            enriched_rows.append({**row, "products": products})
        return enriched_rows

    @staticmethod
    def _best_candidate(match: dict[str, Any]) -> dict[str, Any] | None:
        candidates = list(match.get("candidates") or [])
        selected = match.get("selected")
        if selected:
            selected_id = selected.get("rate_master_id")
            for candidate in candidates:
                if candidate.get("rate_master_id") == selected_id:
                    return {**candidate, **selected}
            return {
                **selected,
                "confidence": match.get("confidence"),
            }
        return candidates[0] if candidates else None
