"""Enrich extracted products with Rate_Master attribute schemas and confidence."""
from __future__ import annotations

from typing import Any

from utils.attribute_parser import (
    attribute_overlap_score,
    normalize_attribute_key,
    normalize_attribute_value,
)


def humanize_attribute_key(key: str) -> str:
    text = str(key or "").strip().replace("_", " ")
    if not text:
        return ""
    if text.upper() == "IS" or text.lower() == "is":
        return "IS Standard"
    return text[:1].upper() + text[1:]


def confidence_band(score: float) -> str:
    """Map attribute confidence to UI color band."""
    if score >= 80:
        return "green"
    if score > 70:
        return "yellow"
    if score > 50:
        return "orange"
    return "red"


def compute_attribute_confidence(
    schema_keys: list[str],
    attributes: dict[str, Any],
    *,
    db_attrs: dict[str, str] | None = None,
) -> float:
    """
    Score 0–100 against the DB attribute schema only.

    Each schema key contributes when the extracted product has a value for it.
    When DB catalog values exist, matching/partial-matching weights the point.
    Empty schema → 0 (never invent 100% from extracted keys alone).
    """
    keys = [str(key) for key in schema_keys if str(key).strip()]
    if not keys:
        return 0.0

    attrs = {
        str(key): str(value).strip()
        for key, value in (attributes or {}).items()
        if value is not None and str(value).strip()
    }
    if not attrs:
        return 0.0

    earned = 0.0
    for key in keys:
        if key not in attrs:
            continue
        if db_attrs and key in db_attrs:
            ratio, _details = attribute_overlap_score({key: attrs[key]}, {key: db_attrs[key]})
            earned += ratio
        else:
            earned += 1.0
    return round(100.0 * earned / len(keys), 2)


def merge_attributes_onto_schema(
    *,
    schema_keys: list[str],
    extracted_attrs: dict[str, Any],
) -> dict[str, str]:
    """Fill DB schema keys using synonym-aware key matching; keep unmatched extras."""
    from utils.attribute_parser import build_alias_map, resolve_to_schema_key

    alias_map = build_alias_map(schema_keys)
    extracted = {
        str(key): normalize_attribute_value(value)
        for key, value in (extracted_attrs or {}).items()
        if value is not None and str(value).strip()
    }
    merged: dict[str, str] = {}
    used_extracted: set[str] = set()

    for raw_key, value in extracted.items():
        schema_key = resolve_to_schema_key(raw_key, schema_keys, aliases=alias_map)
        if schema_key:
            merged.setdefault(schema_key, value)
            used_extracted.add(raw_key)
            continue
        # Already-canonical extracted key that equals a schema key.
        canon = normalize_attribute_key(raw_key, aliases=alias_map)
        if canon in schema_keys:
            merged.setdefault(canon, value)
            used_extracted.add(raw_key)

    for raw_key, value in extracted.items():
        if raw_key in used_extracted:
            continue
        canon = normalize_attribute_key(raw_key, aliases=alias_map)
        if canon in merged or canon in schema_keys:
            continue
        merged[canon] = value
    return merged


def product_needs_attribute_enrichment(product: dict[str, Any]) -> bool:
    """True when Analyse has not yet run AI/DB product+attribute mapping."""
    if "attribute_schema" not in product:
        return True
    if "db_match_status" not in product and product.get("ai_mapping") is None:
        return True
    # Older extracts may have empty schema without an AI mapping attempt.
    if product.get("ai_mapping") is None and not product.get("db_product_id"):
        return True
    return False


def refresh_missing_attribute_keys(product: dict[str, Any]) -> list[str]:
    """Recompute empty DB schema keys after expert edits."""
    schema_keys = [
        str(key)
        for key in (product.get("attribute_schema") or [])
        if str(key).strip()
    ]
    attrs = product.get("attributes") or {}
    return [
        key
        for key in schema_keys
        if attrs.get(key) is None or not str(attrs.get(key)).strip()
    ]
