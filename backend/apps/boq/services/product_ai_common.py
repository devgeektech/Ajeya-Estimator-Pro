"""Shared Product AI mapping constants and helpers."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ai.context import is_catalog_class
from apps.boq.services.boq_row_fields import is_filled as _is_filled, normalize_text as _normalize_text_key
from apps.boq.services.product_matching_service import (
    AI_CANDIDATE_LIMIT,
    CANDIDATE_LIMIT,
    structured_match_score,
)
from apps.database_manager.models import Rate_Master_Output
from common.constants import (
    MATCH_CONFIDENCE_THRESHOLD,
    REFINE_MATCH_CONFIDENCE_TARGET,
)
from utils.attribute_parser import (
    coerce_attributes_dict,
    parse_attributes,
)
from utils.product_synonyms import is_known_material_label

from .product_attribute_enrichment_service import (
    compute_attribute_confidence,
    merge_attributes_onto_schema,
)


_CANDIDATE_LIMIT = CANDIDATE_LIMIT


_AI_CANDIDATE_LIMIT = AI_CANDIDATE_LIMIT


_RECALL_CHROMA_LIMIT = 60


_REMATCH_CHROMA_LIMIT = 80


_REFINE_CHROMA_LIMIT = 30


_REFINE_PASSES = 1


DB_MATCH_MATCHED = "matched"


DB_MATCH_PROVISIONAL = "provisional"


DB_MATCH_UNMATCHED = "unmatched"


_EXPERT_IDENTITY_FIELDS = (
    "description_hint",
    "category",
    "sub_category",
    "class",
    "size",
    "unit",
    "capacity",
)


def _mapping_batch_size() -> int:
    from django.conf import settings

    return max(1, int(getattr(settings, "AI_PRODUCT_MAPPING_BATCH_SIZE", 4) or 4))


def product_needs_match_refine(
    product: dict[str, Any],
    *,
    min_confidence: float = REFINE_MATCH_CONFIDENCE_TARGET,
) -> bool:
    """True when a second mapping pass (like Re-analyse) may improve the match."""
    status = str(product.get("db_match_status") or "").strip().lower()
    if status != DB_MATCH_MATCHED:
        return True
    try:
        confidence = float(product.get("db_match_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence < float(min_confidence)


def _clear_weak_match_inputs(product: dict[str, Any]) -> dict[str, Any]:
    """No-op: keep extract identity and Attribute values that AI already found.

    Weak matches still show the warning banner and hide Product Id until Select /
    strong rematch. Experts should not retype Category/Sub/Size or Attributes
    that Analyse already filled from the BOQ.
    """
    return dict(product)


def _should_blank_weak_match_inputs(
    product: dict[str, Any],
    *,
    confidence: float,
    rematch: bool = False,
) -> bool:
    """Legacy hook — Analyse no longer blanks filled inputs on weak matches."""
    return False


def _restore_expert_identity(
    product: dict[str, Any],
    original: dict[str, Any],
) -> dict[str, Any]:
    """Keep expert-filled Analysis inputs after rematch (including Class=0)."""
    restored = dict(product)
    for key in _EXPERT_IDENTITY_FIELDS:
        value = original.get(key)
        if not _is_filled(value):
            continue
        if (
            key == "class"
            and is_known_material_label(value)
            and not is_catalog_class(
                value,
                category=restored.get("category") or original.get("category"),
                sub_category=restored.get("sub_category") or original.get("sub_category"),
            )
        ):
            # Keep Rate_Master Class (e.g. 0) instead of extracted material (DI).
            continue
        restored[key] = value
    # Keep expert-filled attribute values the user typed before Re-analyse.
    orig_attrs = coerce_attributes_dict(original.get("attributes"))
    if orig_attrs:
        merged_attrs = coerce_attributes_dict(restored.get("attributes"))
        for key, value in orig_attrs.items():
            if _is_filled(value):
                merged_attrs[key] = value
        restored["attributes"] = merged_attrs
    return restored


def _missing_attribute_keys(schema_keys: list[str], attributes: dict[str, Any]) -> list[str]:
    return [
        key
        for key in schema_keys
        if not _is_filled((attributes or {}).get(key))
    ]


def _schema_attributes_from_rate(
    *,
    schema_keys: list[str],
    rate_attrs: dict[str, Any],
    existing_attrs: dict[str, Any] | None = None,
    prefer_rate: bool = False,
) -> dict[str, str]:
    """
    Build Analysis attribute inputs for a Rate_Master Attribute schema.

    ``prefer_rate=True`` (expert candidate select): show the selected DB product's
    values first so Category/attrs match the chosen row. Otherwise keep filled BOQ
    values and only fill blanks from Rate_Master.
    """
    rate_on_schema = merge_attributes_onto_schema(
        schema_keys=schema_keys,
        extracted_attrs=coerce_attributes_dict(rate_attrs),
    )
    existing_on_schema = merge_attributes_onto_schema(
        schema_keys=schema_keys,
        extracted_attrs=coerce_attributes_dict(existing_attrs or {}),
    )
    attributes: dict[str, str] = {}
    for key in schema_keys:
        rate_value = rate_on_schema.get(key)
        existing_value = existing_on_schema.get(key)
        if prefer_rate:
            if _is_filled(rate_value):
                attributes[key] = str(rate_value).strip()
            elif _is_filled(existing_value):
                attributes[key] = str(existing_value).strip()
        elif _is_filled(existing_value):
            attributes[key] = str(existing_value).strip()
        elif _is_filled(rate_value):
            attributes[key] = str(rate_value).strip()
    return attributes


def _json_scalar(value: Any) -> Any:
    """Convert model values (e.g. Decimal) to JSON-safe scalars for analysis_data."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _slim_candidate(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Store/display candidate without inventing fields."""
    return {
        "id": snapshot.get("id"),
        "product_id": snapshot.get("product_id"),
        "rate_id": snapshot.get("rate_id"),
        "tech_key": snapshot.get("tech_key"),
        "category": snapshot.get("category"),
        "sub_category": snapshot.get("sub_category"),
        "class": snapshot.get("class"),
        "size": _json_scalar(snapshot.get("size")),
        "unit": snapshot.get("unit"),
        "capacity": _json_scalar(snapshot.get("capacity")),
        "make": snapshot.get("make"),
        "vendor": snapshot.get("vendor"),
        "attribute_schema": list(snapshot.get("attribute_schema") or []),
        "attributes": dict(snapshot.get("attributes") or {}),
        "confidence": _json_scalar(snapshot.get("confidence")),
        "summary": _product_summary(snapshot),
    }


def _prefer_candidate_first(
    candidates: list[dict[str, Any]],
    selected_id: int | None,
) -> list[dict[str, Any]]:
    """Move the selected/suggested candidate to index 0 when present."""
    if selected_id in (None, ""):
        return list(candidates)
    ordered: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for item in candidates:
        try:
            if int(item.get("id") or 0) == int(selected_id):
                selected = item
                continue
        except (TypeError, ValueError):
            pass
        ordered.append(item)
    if selected is not None:
        return [selected, *ordered]
    return ordered


def _candidate_snapshot(
    rate: Rate_Master_Output,
    *,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Serialize a Rate_Master_Output row for AI/mapping.

    ``id`` / ``rate_master_id`` are both ``Rate_Master_Output.id`` (Django PK). There is
    no ``rate_master_id`` column on the table — that name is only a JSON alias.
    """
    attrs = parse_attributes(rate.Attribute)
    return {
        "id": rate.pk,
        "rate_master_id": rate.pk,  # alias of id for older callers
        "product_id": rate.Product_ID,
        "rate_id": rate.Rate_ID,
        "tech_key": rate.display_key(),
        "category": rate.Category,
        "sub_category": rate.Sub_Category,
        "class": rate.Class,
        "size": _json_scalar(rate.Size),
        "unit": rate.Unit,
        "capacity": _json_scalar(rate.Capacity),
        "make": rate.Make,
        "vendor": rate.Vendor,
        "attribute_schema": list(attrs.keys()),
        "attributes": attrs,
        "confidence": confidence,
    }


def _product_summary(snapshot: dict[str, Any]) -> str:
    # Product_ID is the catalog identity shown on Analysis (not Rate_ID / make).
    parts = [
        snapshot.get("product_id"),
        snapshot.get("category"),
        snapshot.get("sub_category"),
        snapshot.get("class"),
        snapshot.get("size"),
        snapshot.get("unit"),
    ]
    return " / ".join(str(part).strip() for part in parts if _is_filled(part)) or "Matched product"


def _compute_match_confidence(
    extracted: dict[str, Any],
    rate: Rate_Master_Output,
    *,
    mapped_attributes: dict[str, str],
    schema_keys: list[str],
    ai_confidence: float | None,
    prefer_filled_fields: bool = False,
    promote_identity_ceiling: bool = False,
) -> float:
    """Blend structured product score with attribute fill — never make/vendor.

    ``prefer_filled_fields`` (Re-analyse): confidence follows how well the expert's
    filled UI fields match the Rate_Master row — AI may not drag it down for DI vs
    ductile iron wording.

    ``promote_identity_ceiling`` (initial Analyse after Rate-align only): when core
    fields agree at ≥85, show 100%. Re-analyse must not use this — it was forcing
    every rematch to 100%.
    """
    product_only = dict(extracted)
    product_only["make_hint"] = None
    structured, breakdown = structured_match_score(product_only, rate)

    skip_keys = {"make", "manufacturer", "brand", "supplier", "vendor"}
    product_schema = [
        key for key in schema_keys if _normalize_text_key(key) not in skip_keys
    ]
    product_mapped = {
        key: value
        for key, value in (mapped_attributes or {}).items()
        if _normalize_text_key(key) not in skip_keys
    }
    db_attrs = {
        key: value
        for key, value in (parse_attributes(rate.Attribute) or {}).items()
        if _normalize_text_key(key) not in skip_keys
    }
    attr_score = compute_attribute_confidence(
        product_schema,
        product_mapped,
        db_attrs=db_attrs or None,
    )

    # Strong core identity must not stall at 90–92% from AI/attr blend drag.
    core_clean = (
        not breakdown.get("size_mismatch_penalty")
        and not breakdown.get("description_type_mismatch")
    )
    if core_clean and structured >= 95.0:
        return 100.0
    # Initial Analyse Rate-aligned identity only (hose-box style ~85–89% → 100%).
    if promote_identity_ceiling and core_clean and structured >= 85.0:
        return 100.0

    if prefer_filled_fields:
        # Rematch: filled core fields dominate the shown %.
        if product_mapped:
            blended = (0.88 * structured) + (0.12 * float(attr_score or 0.0))
        else:
            blended = structured
        if ai_confidence is not None:
            blended = (0.92 * blended) + (0.08 * float(ai_confidence))
        return round(max(0.0, min(100.0, blended)), 2)

    # Prefer product identity (cat/sub/class/size) over sparse attribute fill so
    # synonym edits like DI → ductile iron do not tank a strong nearest match.
    if structured >= 80:
        blended = (0.82 * structured) + (0.18 * (attr_score or structured))
    elif structured >= 60:
        blended = (0.70 * structured) + (0.30 * (attr_score or structured))
    elif product_schema:
        blended = (0.60 * structured) + (0.40 * attr_score)
    else:
        blended = structured
    if ai_confidence is not None:
        # AI may under-score synonym rewrites; keep structured dominant when strong.
        ai_weight = 0.15 if structured >= 75 else 0.30
        blended = ((1.0 - ai_weight) * blended) + (ai_weight * float(ai_confidence))
    # Soft lift: near-perfect structured with no hard conflict → full credit.
    if core_clean and structured >= 92.0 and blended >= 88.0:
        return 100.0
    return round(max(0.0, min(100.0, blended)), 2)


def _downgrade_unrelated_auto_match(
    product: dict[str, Any],
    confidence: float,
) -> dict[str, Any]:
    """Clear a confirmed pick when description and catalog product disagree."""
    source = str((product.get("ai_mapping") or {}).get("selection_source") or "")
    if source == "expert":
        return product
    if confidence >= MATCH_CONFIDENCE_THRESHOLD:
        return product
    if str(product.get("db_match_status") or "") != DB_MATCH_MATCHED:
        return product
    updated = dict(product)
    updated["db_match_status"] = DB_MATCH_PROVISIONAL
    updated["db_product_id"] = None
    updated["db_product_tech_key"] = ""
    summary = str(updated.get("db_product_summary") or "").strip()
    if summary and not summary.lower().startswith("suggested:"):
        updated["db_product_summary"] = f"Suggested: {summary}"
    mapping = dict(updated.get("ai_mapping") or {})
    mapping["match_status"] = DB_MATCH_PROVISIONAL
    mapping["selected_id"] = None
    mapping["selected_rate_master_id"] = None
    updated["ai_mapping"] = mapping
    return updated


def _map_attrs_onto_schema(
    *,
    schema_keys: list[str],
    extracted_attrs: dict[str, str],
    attribute_map: dict[str, str],
    mapped_attributes: dict[str, str],
    unmapped_attributes: dict[str, str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Resolve AI + extracted attributes onto a Rate_Master_Output Attribute schema."""
    from utils.attribute_parser import build_alias_map, resolve_to_schema_key

    alias_map = build_alias_map(schema_keys)
    attr_map = dict(attribute_map)
    mapped = dict(mapped_attributes)
    unmapped = dict(unmapped_attributes)

    if attr_map:
        attr_map = {
            src: (resolve_to_schema_key(dst, schema_keys, aliases=alias_map) or dst)
            for src, dst in attr_map.items()
        }

    if mapped:
        resolved_mapped: dict[str, str] = {}
        for key, value in mapped.items():
            schema_key = resolve_to_schema_key(key, schema_keys, aliases=alias_map) or key
            if schema_key in schema_keys:
                resolved_mapped[schema_key] = value
            else:
                unmapped.setdefault(key, value)
        mapped = resolved_mapped

    if not mapped and attr_map:
        for src, dst in attr_map.items():
            if src in extracted_attrs and dst in schema_keys:
                mapped[dst] = extracted_attrs[src]

    if not mapped:
        merged_all = merge_attributes_onto_schema(
            schema_keys=schema_keys,
            extracted_attrs=extracted_attrs,
        )
        mapped = {key: value for key, value in merged_all.items() if key in schema_keys}
        unmapped = {key: value for key, value in merged_all.items() if key not in schema_keys}
    elif not unmapped:
        mapped_keys = set(mapped)
        mapped_keys.update(attr_map.values())
        unmapped = {
            key: value
            for key, value in extracted_attrs.items()
            if key not in mapped_keys
            and resolve_to_schema_key(key, schema_keys, aliases=alias_map) is None
        }

    return mapped, unmapped, attr_map

