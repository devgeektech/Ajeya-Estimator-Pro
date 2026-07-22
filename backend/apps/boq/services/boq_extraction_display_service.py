"""Shape extracted products/activities for the BOQ detail Analysis tab."""
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
from utils.attribute_parser import coerce_attributes_dict, normalize_attribute_key

_PRODUCT_FIELDS: tuple[tuple[str, str], ...] = (
    ("description_hint", "Product description"),
    ("category", "Category"),
    ("sub_category", "Sub-category"),
    ("class", "Class"),
    ("size", "Size"),
    ("capacity", "Capacity"),
    ("unit", "Unit"),
)

# Product scalars shown in the card — never repeated under Additional Attributes.
_PRODUCT_FIELD_KEYS: frozenset[str] = frozenset(key for key, _label in _PRODUCT_FIELDS) | frozenset(
    ("make_hint", "quantity", "quantity_unit")
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
    Attributes grid = DB schema keys (filled when AI found a value, else empty).
    Additional Attributes = AI keys not in the DB schema or product field grid.
    """
    attrs = coerce_attributes_dict(product.get("attributes"))
    schema_keys = [
        str(key)
        for key in (product.get("attribute_schema") or [])
        if str(key).strip()
    ]
    schema_set = {normalize_attribute_key(key) for key in schema_keys}
    exclude_keys = schema_set | {normalize_attribute_key(key) for key in _PRODUCT_FIELD_KEYS}

    # Always render the full DB schema — empty inputs for keys AI did not find.
    fields = [
        {
            "key": key,
            "label": _attribute_label(key),
            "value": "" if _is_blank(attrs.get(key)) else str(attrs.get(key)),
            "filled": not _is_blank(attrs.get(key)),
        }
        for key in schema_keys
    ]

    # AI-only attributes (not schema keys or product card fields).
    extra = []
    for key, value in sorted(attrs.items()):
        if _is_blank(value):
            continue
        canon = normalize_attribute_key(str(key))
        if canon in exclude_keys:
            continue
        extra.append({"key": key, "value": value})

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
        "extra": extra,
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
    for item in (product.get("db_candidates") or [])[:5]:
        candidates.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary")
                or _product_summary(item),
                "tech_key": item.get("tech_key") or "",
                "confidence": item.get("confidence"),
            }
        )

    return {
        "product_index": int(product.get("product_index") or 0),
        "source_row_id": source_row_id,
        "display_number": display_number,
        "display_label": f"Product {display_number}" + (f" of {total}" if total > 1 else ""),
        "is_user_added": (product.get("source") or "").lower() == "user",
        "fields": fields,
        "attributes": attribute_fields,
        "extra_attrs_json": json.dumps(attribute_fields.get("extra") or []),
        "attribute_schema_json": json.dumps(
            [field["key"] for field in attribute_fields.get("fields") or []]
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

    activities: list[str] = []
    for row_id in lineage_ids:
        analysis_row = analysis_by_row.get(str(row_id), {})
        for activity in analysis_row.get("activities") or []:
            if activity not in activities:
                activities.append(activity)

    if not activities:
        activities = list(anchor_analysis.get("activities") or [])

    return products, activities, anchor_analysis


def build_product_save_feedback(product: dict[str, Any]) -> dict[str, Any]:
    """Return UI feedback fields after saving a product."""
    shaped = _shape_product(
        product,
        display_number=int(product.get("product_index") or 0) + 1,
        total=1,
        source_row_id=str(product.get("source_row_id") or ""),
    )
    return {
        "missing_count": shaped["missing_count"],
        "summary": shaped["summary"],
        "is_complete": shaped["missing_count"] == 0,
        "attribute_confidence": shaped["attribute_confidence"],
        "attribute_confidence_band": shaped["attribute_confidence_band"],
    }


class BOQExtractionDisplayService:
    """Build upload-order rows showing AI-extracted products and activities."""

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
        activity_count = 0
        missing_field_count = 0

        for group in grouped_anchor_rows(boq_data):
            row_id = group["row_id"]
            products, activities, analysis_row = _merge_lineage_analysis(
                group["group_ids"],
                analysis_by_row,
            )
            product_total = len(products)
            shaped_products = [
                _shape_product(
                    product,
                    display_number=index + 1,
                    total=product_total,
                    source_row_id=str(product.get("source_row_id") or row_id),
                )
                for index, product in enumerate(products)
            ]
            product_count += len(products)
            activity_count += len(activities)
            missing_field_count += sum(product["missing_count"] for product in shaped_products)

            category, sub_category = _primary_category(products)
            if analysis_row.get("skip_matching") and not products and not activities:
                status = "skipped"
            elif products or activities:
                status = "extracted"
            elif analysis_row:
                status = "empty"
            else:
                status = "not_analyzed"

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
                    "rate_only": bool(group.get("rate_only")),
                    "boq_rate": group.get("boq_rate"),
                    "status": status,
                    "product_count": product_total,
                    "products": shaped_products,
                    "activities": activities,
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
            "activity_count": activity_count,
            "missing_field_count": missing_field_count,
            "has_make_list": self.has_make_list_file and self.make_list_service.has_constraints,
            "lines": lines,
        }
