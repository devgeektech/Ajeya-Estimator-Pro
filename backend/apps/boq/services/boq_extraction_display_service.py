"""Shape extracted products for the BOQ detail Analysis tab."""
from __future__ import annotations

import json
from typing import Any

from apps.boq.models import BOQ
from apps.boq.services.boq_extraction_service import _normalize_product_fields
from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows
from apps.boq.services.extraction_attribute_fields import COMMON_ATTRIBUTE_LABELS
from apps.boq.services.make_list_constraint_service import MakeListConstraintService
from apps.boq.services.product_attribute_enrichment_service import (
    compute_attribute_confidence,
    confidence_band,
    humanize_attribute_key,
)
from apps.boq.services.product_matching_service import structured_match_score
from apps.database_manager.models import Rate_Master
from utils.attribute_parser import coerce_attributes_dict


def _candidate_confidence_value(raw: Any) -> float | None:
    """Normalize stored retrieval/match confidence for Analysis display."""
    if raw in (None, ""):
        return None
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def _backfill_candidate_confidences(
    product: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    database_version_id: int | None,
) -> None:
    """Fill missing candidate % from structured score (legacy wiped scores)."""
    if not database_version_id:
        return
    missing_ids: list[int] = []
    for item in candidates:
        if item.get("confidence") is not None:
            continue
        try:
            cand_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        missing_ids.append(cand_id)
    if not missing_ids:
        return
    rates = {
        rate.pk: rate
        for rate in Rate_Master.objects.filter(
            pk__in=missing_ids,
            database_version_id=database_version_id,
        )
    }
    product_only = dict(product)
    product_only["make_hint"] = None
    for item in candidates:
        if item.get("confidence") is not None:
            continue
        try:
            cand_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        rate = rates.get(cand_id)
        if rate is None:
            continue
        score, _breakdown = structured_match_score(product_only, rate)
        item["confidence"] = round(float(score), 2)


_PRODUCT_FIELDS: tuple[tuple[str, str], ...] = (
    ("description_hint", "Product description"),
    ("category", "Category"),
    ("sub_category", "Sub-category"),
    ("class", "Class"),
    ("size", "Size"),
    ("capacity", "Capacity"),
    ("unit", "Unit"),
)

# All product property fields are optional — products differ in which apply.
_REQUIRED_FIELDS: frozenset[str] = frozenset()


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _attribute_label(key: str) -> str:
    return COMMON_ATTRIBUTE_LABELS.get(key) or humanize_attribute_key(key)


def _shape_attribute_fields(product: dict[str, Any]) -> dict[str, Any]:
    """
    Attributes grid = required DB schema keys only (filled when AI/expert found a value).
    Experts can add more via the Attributes + control.
    """
    attrs = coerce_attributes_dict(product.get("attributes"))
    schema_keys = [
        str(key)
        for key in (product.get("attribute_schema") or [])
        if str(key).strip()
    ]

    # Needed DB schema attributes only — never show free-form additional attributes.
    fields = [
        {
            "key": key,
            "label": _attribute_label(key),
            "value": "" if _is_blank(attrs.get(key)) else str(attrs.get(key)),
            "filled": not _is_blank(attrs.get(key)),
            "removable": False,
        }
        for key in schema_keys
    ]

    confidence = product.get("attribute_confidence")
    if confidence is None:
        confidence = (
            compute_attribute_confidence(schema_keys, attrs)
            if schema_keys
            else 0.0
        )
    confidence = float(confidence or 0.0)
    source = product.get("attribute_source") or ("database" if schema_keys else "extracted")
    return {
        "fields": fields,
        "extra": [],
        "confidence": confidence,
        "confidence_band": confidence_band(confidence),
        "source": source,
        "has_db_schema": bool(schema_keys),
    }


def _shape_product(
    product: dict[str, Any],
    *,
    display_number: int,
    total: int,
    source_row_id: str,
    database_version_id: int | None = None,
) -> dict[str, Any]:
    product = _normalize_product_fields(product)
    fields: list[dict[str, Any]] = []
    missing_count = 0
    for key, label in _PRODUCT_FIELDS:
        value = product.get(key)
        missing = _is_blank(value) and key in _REQUIRED_FIELDS
        if missing:
            missing_count += 1
        fields.append(
            {
                "key": key,
                "label": label,
                "value": value if value is not None else "",
                "missing": missing,
            }
        )

    attribute_fields = _shape_attribute_fields(product)
    missing_attr_keys = [
        str(key)
        for key in (product.get("missing_attribute_keys") or [])
        if str(key).strip()
    ]
    if not missing_attr_keys:
        missing_attr_keys = [
            field["key"]
            for field in attribute_fields.get("fields") or []
            if not field.get("filled")
        ]

    db_match_status = str(product.get("db_match_status") or "").strip() or (
        "matched" if product.get("db_product_id") else "unmatched"
    )
    db_match = None
    if product.get("db_product_id") or product.get("db_product_summary") or db_match_status == "provisional":
        db_match = {
            "rate_master_id": product.get("db_product_id"),
            "suggested_id": product.get("suggested_db_product_id"),
            "status": db_match_status,
            "summary": product.get("db_product_summary")
            or _product_summary(
                {
                    "category": product.get("category"),
                    "sub_category": product.get("sub_category"),
                    "class": product.get("class"),
                    "size": product.get("size"),
                }
            ),
            "make": product.get("db_product_make") or "",
            "tech_key": product.get("db_product_tech_key") or "",
            "notes": ((product.get("ai_mapping") or {}).get("notes") or ""),
            "missing_attribute_keys": missing_attr_keys,
        }

    candidates = []
    selected_id = product.get("db_product_id") or product.get("suggested_db_product_id")
    selected_confidence = _candidate_confidence_value(
        product.get("db_match_confidence")
    )
    if selected_confidence is None:
        selected_confidence = _candidate_confidence_value(
            product.get("attribute_confidence")
        )
    for item in (product.get("db_candidates") or [])[:3]:
        cand_id = item.get("id")
        is_selected = False
        try:
            if cand_id is not None and selected_id is not None:
                is_selected = int(cand_id) == int(selected_id)
        except (TypeError, ValueError):
            is_selected = False
        confidence = _candidate_confidence_value(item.get("confidence"))
        # Older refine passes wiped retrieval scores; still show % for the
        # selected/suggested row from the product-level match score.
        if confidence is None and is_selected:
            confidence = selected_confidence
        candidates.append(
            {
                "id": cand_id,
                "summary": item.get("summary")
                or _product_summary(item),
                "tech_key": item.get("tech_key") or "",
                "confidence": confidence,
                "is_selected": is_selected,
            }
        )
    # Skip invented scores after an expert pick — keep other candidates' stored %.
    selection_source = str((product.get("ai_mapping") or {}).get("selection_source") or "")
    if selection_source != "expert":
        _backfill_candidate_confidences(
            product,
            candidates,
            database_version_id=database_version_id,
        )

    return {
        "product_index": int(product.get("product_index") or 0),
        "source_row_id": source_row_id,
        "display_number": display_number,
        "display_label": f"Product {display_number}" + (f" of {total}" if total > 1 else ""),
        "is_user_added": (product.get("source") or "").lower() == "user",
        "fields": fields,
        "attributes": attribute_fields,
        "extra_attrs_json": json.dumps([]),
        "attribute_schema_json": json.dumps(
            [
                field["key"]
                for field in attribute_fields.get("fields") or []
                if not field.get("removable")
            ]
        ),
        "attribute_confidence": attribute_fields["confidence"],
        "attribute_confidence_band": attribute_fields["confidence_band"],
        "db_match": db_match,
        "db_match_status": db_match_status,
        "db_candidates": candidates,
        "missing_attribute_keys": missing_attr_keys,
        "missing_attribute_count": len(missing_attr_keys),
        "missing_count": missing_count,
        "summary": _product_summary(product),
        "raw": product,
    }


def _product_summary(product: dict[str, Any]) -> str:
    parts = [
        product.get("description_hint"),
        product.get("category"),
        product.get("sub_category"),
        product.get("class"),
    ]
    size = product.get("size")
    unit = product.get("unit")
    if size not in (None, ""):
        parts.append(f"{size}{unit or ''}")
    capacity = product.get("capacity")
    if capacity not in (None, ""):
        parts.append(str(capacity))
    return " / ".join(str(part) for part in parts if part not in (None, "")) or "Product"


def _primary_category(products: list[dict[str, Any]]) -> tuple[str, str]:
    if not products:
        return "", ""
    first = products[0]
    return str(first.get("category") or ""), str(first.get("sub_category") or "")


def _shape_make_list(
    *,
    full_description: str,
    stored: dict[str, Any] | None,
    make_list_service: MakeListConstraintService,
    category: str = "",
    sub_category: str = "",
    has_make_list_file: bool = False,
) -> dict[str, Any]:
    options_data = make_list_service.make_options_for_product(
        category=category,
        sub_category=sub_category,
        description=full_description,
    )
    stored_data = stored or {}
    make_options = list(options_data.get("make_options") or [])
    if not make_options:
        make_options = make_list_service.all_approved_makes()
    for make in stored_data.get("approved_makes") or []:
        if make not in make_options:
            make_options.append(make)

    selected = stored_data.get("selected_make") or ""
    prefer_lowest = bool(stored_data.get("prefer_lowest_price")) or (
        MakeListConstraintService.is_lowest_make_selection(selected)
    )
    if not make_list_service.has_constraints and not selected:
        prefer_lowest = True
    is_custom = (not prefer_lowest) and (
        bool(stored_data.get("custom_make"))
        or (selected and selected not in make_options)
    )
    return {
        "has_make_list": has_make_list_file and bool(make_list_service.has_constraints or make_options),
        "matched": bool(options_data.get("matched") or stored_data),
        "material": stored_data.get("material") or options_data.get("material") or "",
        "category_material": options_data.get("category_material") or "",
        "mapped_category": options_data.get("mapped_category") or category or "",
        "selection_basis": options_data.get("selection_basis") or "",
        "approved_makes": make_options,
        "make_options": make_options,
        "selected_make": selected,
        "custom_make": stored_data.get("custom_make") or (selected if is_custom else ""),
        "is_custom_make": is_custom,
        "is_lowest_make": prefer_lowest,
        "prefer_lowest_price": prefer_lowest,
        "match_score": stored_data.get("match_score") or options_data.get("match_score"),
    }


def _merge_lineage_analysis(
    lineage_ids: list[str],
    analysis_by_row: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    anchor_id = str(lineage_ids[0]) if lineage_ids else ""
    anchor_analysis = analysis_by_row.get(anchor_id, {})

    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_id in lineage_ids:
        analysis_row = analysis_by_row.get(str(row_id), {})
        for product in analysis_row.get("products") or []:
            dedupe_key = "|".join(
                [
                    str(product.get("description_hint") or ""),
                    str(product.get("category") or ""),
                    str(product.get("sub_category") or ""),
                    str(product.get("product_index") or ""),
                ]
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            products.append({**product, "source_row_id": str(row_id)})

    for index, product in enumerate(products):
        product["product_index"] = index

    # Activities are retired — Analysis extracts products only.
    return products, [], anchor_analysis


def build_product_save_feedback(product: dict[str, Any]) -> dict[str, Any]:
    """Return UI feedback fields after saving a product."""
    shaped = _shape_product(
        product,
        display_number=int(product.get("product_index") or 0) + 1,
        total=1,
        source_row_id=str(product.get("source_row_id") or ""),
        database_version_id=None,
    )
    return {
        "missing_count": shaped["missing_count"],
        "summary": shaped["summary"],
        "is_complete": shaped["missing_count"] == 0,
        "attribute_confidence": shaped["attribute_confidence"],
        "attribute_confidence_band": shaped["attribute_confidence_band"],
    }


class BOQExtractionDisplayService:
    """Build upload-order rows showing AI-extracted products."""

    def __init__(self, boq: BOQ, make_list_data: dict | None = None, *, has_make_list_file: bool = False):
        self.boq = boq
        self.has_make_list_file = has_make_list_file
        self.make_list_service = MakeListConstraintService(make_list_data)

    def build(self) -> dict[str, Any]:
        analysis = self.boq.analysis_data or {}
        boq_data = self.boq.boq_data or {}
        analysis_by_row = {
            str(row.get("row_id")): row
            for row in analysis.get("rows") or []
            if row.get("row_id")
        }

        lines: list[dict[str, Any]] = []
        product_count = 0
        missing_field_count = 0
        multiproduct_review_count = 0

        db_version_id = int((analysis.get("database_version_id") or 0) or 0) or None
        if not db_version_id:
            from apps.database_manager.services.activation import get_active_database_version

            active = get_active_database_version()
            db_version_id = active.pk if active else None

        for group in grouped_anchor_rows(boq_data):
            row_id = group["row_id"]
            products, _activities, analysis_row = _merge_lineage_analysis(
                group["group_ids"],
                analysis_by_row,
            )
            product_total = len(products)
            qty_rows = list(group.get("qty_rows") or [])
            qty_row_count = len(qty_rows)
            # More products than Unit/Qty rows → expert should review (e.g. 1 qty, 2 products).
            multiproduct_review = product_total >= 2 and product_total > qty_row_count

            shaped_products = [
                _shape_product(
                    product,
                    display_number=index + 1,
                    total=product_total,
                    source_row_id=str(product.get("source_row_id") or row_id),
                    database_version_id=db_version_id,
                )
                for index, product in enumerate(products)
            ]
            product_count += len(products)
            missing_field_count += sum(product["missing_count"] for product in shaped_products)
            if multiproduct_review:
                multiproduct_review_count += 1

            category, sub_category = _primary_category(products)
            if analysis_row.get("skip_matching") and not products:
                status = "skipped"
            elif products:
                status = "extracted"
            elif analysis_row:
                status = "empty"
            else:
                status = "not_analyzed"

            # Pure section headers (no products) are merged into product groups — hide them.
            if status == "skipped" and analysis_row.get("skip_reason") != "ai_missing_row":
                continue

            lines.append(
                {
                    "row_id": row_id,
                    "serial": group.get("serial", ""),
                    "depth": group.get("depth", 0),
                    "description": group.get("description") or "",
                    "full_description": group.get("full_description") or group.get("description") or "",
                    "lineage_parts": group.get("lineage_parts") or [],
                    "lineage_count": group.get("lineage_count") or 1,
                    "primary_category": category,
                    "primary_sub_category": sub_category,
                    "qty": group.get("qty"),
                    "unit": group.get("unit"),
                    "qty_status": group.get("qty_status"),
                    "qty_row_count": qty_row_count,
                    "rate_only": bool(group.get("rate_only")),
                    "boq_rate": group.get("boq_rate"),
                    "status": status,
                    "skip_reason": analysis_row.get("skip_reason") or "",
                    "product_count": product_total,
                    "multiproduct_review": multiproduct_review,
                    "products": shaped_products,
                    "activities": [],
                    "make_list": _shape_make_list(
                        full_description=group.get("full_description") or "",
                        stored=analysis_row.get("make_list"),
                        make_list_service=self.make_list_service,
                        category=category,
                        sub_category=sub_category,
                        has_make_list_file=self.has_make_list_file,
                    ),
                }
            )

        stats = analysis.get("stats") or {}
        return {
            "has_extraction": bool(analysis.get("rows")),
            "phase": analysis.get("phase"),
            "stats": stats,
            "product_count": product_count,
            "activity_count": 0,
            "missing_field_count": missing_field_count,
            "multiproduct_review_count": multiproduct_review_count,
            "has_make_list": self.has_make_list_file and self.make_list_service.has_constraints,
            "lines": lines,
        }
