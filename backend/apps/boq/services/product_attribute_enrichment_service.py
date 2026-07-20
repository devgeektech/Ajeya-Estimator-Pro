"""Enrich extracted products with Rate_Master attribute schemas and confidence."""
from __future__ import annotations

import logging
from typing import Any

from apps.boq.services.product_matching_service import ProductMatchingService
from apps.database_manager.models import Rate_Master
from common.constants import MATCH_CONFIDENCE_THRESHOLD
from utils.attribute_parser import (
    attribute_overlap_score,
    coerce_attributes_dict,
    normalize_attribute_key,
    normalize_attribute_value,
    parse_attributes,
)

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


class ProductAttributeEnrichmentService:
    """Search Rate_Master, apply DB attribute keys, score fill confidence."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id
        self._matcher = ProductMatchingService(database_version_id)

    def enrich_product(self, product: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(product)
        extracted_attrs = coerce_attributes_dict(enriched.get("attributes"))

        rate, match_meta = self._resolve_rate_master(enriched)
        if rate is None:
            # No DB product — UI shows empty Attributes schema; AI keys as Additional.
            enriched["attributes"] = extracted_attrs
            enriched["attribute_schema"] = []
            enriched["missing_attribute_keys"] = []
            enriched["attribute_confidence"] = 0.0
            enriched["attribute_source"] = "extracted"
            enriched["db_match_status"] = "unmatched"
            enriched["db_product_id"] = None
            enriched["db_product_tech_key"] = ""
            return enriched

        db_attrs = parse_attributes(rate.Attribute)
        # Schema is always the DB Attribute keys (empty value in UI when AI missed it).
        schema_keys = list(db_attrs.keys())
        filled = merge_attributes_onto_schema(
            schema_keys=schema_keys,
            extracted_attrs=extracted_attrs,
        )
        confidence = compute_attribute_confidence(
            schema_keys,
            filled,
            db_attrs=db_attrs or None,
        )
        match_confidence = float(match_meta.get("confidence") or 0)
        missing = refresh_missing_attribute_keys(
            {"attribute_schema": schema_keys, "attributes": filled}
        )

        enriched["attributes"] = filled
        enriched["attribute_schema"] = schema_keys
        enriched["missing_attribute_keys"] = missing
        enriched["attribute_confidence"] = confidence
        enriched["attribute_source"] = "database" if schema_keys else "extracted"
        enriched["db_match_confidence"] = match_confidence
        if match_confidence >= MATCH_CONFIDENCE_THRESHOLD:
            enriched["db_match_status"] = "matched"
            enriched["db_product_id"] = rate.pk
            enriched["db_product_make"] = rate.Make
            enriched["db_product_tech_key"] = rate.Tech_Key
        else:
            # Schema for gap-fill only — do not invent a confirmed product link.
            enriched["db_match_status"] = "provisional"
            enriched["db_product_id"] = None
            enriched["db_product_make"] = ""
            enriched["db_product_tech_key"] = ""
            enriched["suggested_db_product_id"] = rate.pk
        return enriched

    def enrich_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        only_missing: bool = False,
    ) -> list[dict[str, Any]]:
        enriched_rows: list[dict[str, Any]] = []
        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                enriched_rows.append(row)
                continue
            updated_products: list[dict[str, Any]] = []
            for product in products:
                if only_missing and not product_needs_attribute_enrichment(product):
                    updated_products.append(product)
                else:
                    updated_products.append(self.enrich_product(product))
            enriched_rows.append({**row, "products": updated_products})
        return enriched_rows

    def _resolve_rate_master(
        self,
        extracted: dict[str, Any],
    ) -> tuple[Rate_Master | None, dict[str, Any]]:
        """Prefer fast SQL structured match; fall back to Chroma matching."""
        sql_best = self._best_sql_rate(extracted)
        if sql_best is not None:
            return sql_best

        try:
            match = self._matcher.match_product(extracted)
        except Exception:
            logger.exception("Chroma attribute enrichment match failed")
            return None, {}

        best = self._best_candidate(match)
        if best is None:
            return None, {}
        rate = Rate_Master.objects.filter(
            pk=best["rate_master_id"],
            database_version_id=self.database_version_id,
        ).first()
        return rate, {
            "confidence": best.get("confidence"),
            "rate_master_id": best.get("rate_master_id"),
        }

    def _best_sql_rate(
        self,
        extracted: dict[str, Any],
    ) -> tuple[Rate_Master | None, dict[str, Any]] | None:
        candidates = self._matcher._sql_fallback_candidates(extracted)
        if not candidates:
            # Broader retry: category + sub_category only (ignore size mismatch).
            broad = dict(extracted)
            broad["size"] = None
            candidates = self._matcher._sql_fallback_candidates(broad)
        if not candidates:
            return None

        candidates.sort(key=lambda item: item.get("confidence") or 0.0, reverse=True)
        best = candidates[0]
        rate = best.get("rate")
        if rate is None:
            return None
        # Prefer rows that actually define Attribute keys when scores are close.
        with_attrs = [
            item
            for item in candidates[:10]
            if item.get("rate") is not None and parse_attributes(item["rate"].Attribute)
        ]
        if with_attrs and (best.get("confidence") or 0) - (with_attrs[0].get("confidence") or 0) <= 5:
            best = with_attrs[0]
            rate = best["rate"]
        return rate, {
            "confidence": best.get("confidence"),
            "rate_master_id": rate.pk,
        }

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
