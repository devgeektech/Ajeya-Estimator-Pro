"""Shape extracted products/activities for the BOQ detail Analysis tab."""
from __future__ import annotations

from typing import Any

from apps.boq.models import BOQ
from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows
from apps.boq.services.extraction_attribute_fields import COMMON_ATTRIBUTE_FIELDS, COMMON_ATTRIBUTE_KEYS
from apps.boq.services.make_list_constraint_service import MakeListConstraintService

_PRODUCT_FIELDS: tuple[tuple[str, str], ...] = (
    ("description_hint", "Product description"),
    ("category", "Category"),
    ("sub_category", "Sub-category"),
    ("class", "Class"),
    ("size", "Size"),
    ("unit", "Unit"),
    ("capacity", "Capacity"),
    ("quantity", "Quantity"),
    ("quantity_unit", "Qty unit"),
)

_OPTIONAL_MISSING_FIELDS = {"description_hint", "quantity", "quantity_unit"}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _shape_attribute_fields(attributes: dict[str, Any]) -> dict[str, Any]:
    attrs = attributes or {}
    common = [
        {
            "key": key,
            "label": label,
            "value": attrs.get(key, "") or "",
        }
        for key, label in COMMON_ATTRIBUTE_FIELDS
    ]
    extra = [
        {"key": key, "value": value}
        for key, value in sorted(attrs.items())
        if key not in COMMON_ATTRIBUTE_KEYS
    ]
    return {"common": common, "extra": extra}


def _shape_product(
    product: dict[str, Any],
    *,
    display_number: int,
    total: int,
    source_row_id: str,
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    missing_count = 0
    for key, label in _PRODUCT_FIELDS:
        value = product.get(key)
        missing = _is_blank(value) and key not in _OPTIONAL_MISSING_FIELDS
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

    attributes = product.get("attributes") or {}
    attribute_fields = _shape_attribute_fields(attributes)

    return {
        "product_index": int(product.get("product_index") or 0),
        "source_row_id": source_row_id,
        "display_number": display_number,
        "display_label": f"Product {display_number}" + (f" of {total}" if total > 1 else ""),
        "is_user_added": (product.get("source") or "").lower() == "user",
        "fields": fields,
        "attributes": attribute_fields,
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
) -> dict[str, Any]:
    options_data = make_list_service.make_options_for_product(
        category=category,
        sub_category=sub_category,
        description=full_description,
    )
    stored_data = stored or {}
    make_options = list(options_data.get("make_options") or [])
    for make in stored_data.get("approved_makes") or []:
        if make not in make_options:
            make_options.append(make)

    selected = stored_data.get("selected_make") or ""
    is_custom = bool(stored_data.get("custom_make")) or (
        selected and selected not in make_options
    )
    return {
        "has_make_list": make_list_service.has_constraints,
        "matched": bool(options_data.get("matched") or stored_data),
        "material": stored_data.get("material") or options_data.get("material") or "",
        "category_material": options_data.get("category_material") or "",
        "approved_makes": make_options,
        "make_options": make_options,
        "selected_make": selected,
        "custom_make": stored_data.get("custom_make") or (selected if is_custom else ""),
        "is_custom_make": is_custom,
        "match_score": stored_data.get("match_score") or options_data.get("match_score"),
    }


def _merge_lineage_analysis(
    lineage_ids: list[str],
    analysis_by_row: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    products: list[dict[str, Any]] = []
    activities: list[str] = []
    anchor_analysis: dict[str, Any] = {}

    for row_id in lineage_ids:
        analysis_row = analysis_by_row.get(row_id, {})
        if not anchor_analysis and analysis_row:
            anchor_analysis = analysis_row
        for activity in analysis_row.get("activities") or []:
            if activity not in activities:
                activities.append(activity)
        for product in analysis_row.get("products") or []:
            products.append({**product, "source_row_id": row_id})

    if not anchor_analysis and lineage_ids:
        anchor_analysis = analysis_by_row.get(lineage_ids[0], {})

    return products, activities, anchor_analysis


class BOQExtractionDisplayService:
    """Build upload-order rows showing AI-extracted products and activities."""

    def __init__(self, boq: BOQ, make_list_data: dict | None = None):
        self.boq = boq
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
                group["lineage_ids"],
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
                    "description": group.get("full_description") or group.get("description") or "",
                    "lineage_parts": group.get("lineage_parts") or [],
                    "lineage_count": group.get("lineage_count") or 1,
                    "primary_category": category,
                    "primary_sub_category": sub_category,
                    "qty": group.get("qty"),
                    "unit": group.get("unit"),
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
            "has_make_list": self.make_list_service.has_constraints,
            "lines": lines,
        }
