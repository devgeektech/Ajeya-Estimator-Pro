"""Shape extracted products/activities for the BOQ detail Analysis tab."""
from __future__ import annotations

import json
from typing import Any

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_display_service import _field_from_map, _ordered_boq_rows
from apps.boq.services.make_list_constraint_service import MakeListConstraintService
from apps.boq.services.serial_normalizer import analysis_fields

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_UNIT_KEYS = ("unit", "uom")

_PRODUCT_FIELDS: tuple[tuple[str, str], ...] = (
    ("description_hint", "Product description"),
    ("category", "Category"),
    ("sub_category", "Sub-category"),
    ("class", "Class"),
    ("size", "Size"),
    ("unit", "Unit"),
    ("capacity", "Capacity"),
    ("make_hint", "Make hint"),
    ("quantity", "Quantity"),
    ("quantity_unit", "Qty unit"),
)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


_OPTIONAL_MISSING_FIELDS = {"description_hint", "make_hint", "quantity", "quantity_unit"}


def _shape_product(product: dict[str, Any], *, display_number: int, total: int) -> dict[str, Any]:
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
    attr_rows = [
        {"key": key, "value": value}
        for key, value in sorted(attributes.items())
    ]

    return {
        "product_index": int(product.get("product_index") or 0),
        "display_number": display_number,
        "display_label": f"Product {display_number}" + (f" of {total}" if total > 1 else ""),
        "is_user_added": (product.get("source") or "").lower() == "user",
        "fields": fields,
        "attributes": attr_rows,
        "attributes_json_text": json.dumps(attributes, ensure_ascii=False, indent=2)
        if attributes
        else "{}",
        "missing_count": missing_count,
        "summary": _product_summary(product),
        "raw": product,
    }


def _product_summary(product: dict[str, Any]) -> str:
    parts = [
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


def _shape_make_list(
    *,
    description: str,
    stored: dict[str, Any] | None,
    make_list_service: MakeListConstraintService,
) -> dict[str, Any]:
    matched = make_list_service.match_for_description(description)
    if not matched and not stored:
        return {
            "has_make_list": make_list_service.has_constraints,
            "matched": False,
            "material": "",
            "approved_makes": [],
            "selected_make": "",
            "match_score": None,
        }

    stored_data = stored or {}
    matched_data = matched or {}
    approved = list(stored_data.get("approved_makes") or matched_data.get("approved_makes") or [])
    selected = stored_data.get("selected_make") or ""
    return {
        "has_make_list": make_list_service.has_constraints,
        "matched": bool(matched or stored),
        "material": stored_data.get("material") or matched_data.get("material") or "",
        "approved_makes": approved,
        "selected_make": selected,
        "match_score": stored_data.get("match_score") or matched_data.get("match_score"),
    }


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

        for boq_row in _ordered_boq_rows(boq_data):
            row_id = str(boq_row.get("row_id") or "")
            if not row_id:
                continue

            analysis_row = analysis_by_row.get(row_id, {})
            fields = analysis_fields(boq_row)
            description = _field_from_map(fields, _DESCRIPTION_KEYS) or ""
            products = list(analysis_row.get("products") or [])
            activities = list(analysis_row.get("activities") or [])
            product_total = len(products)
            shaped_products = [
                _shape_product(product, display_number=index + 1, total=product_total)
                for index, product in enumerate(products)
            ]
            product_count += len(products)
            activity_count += len(activities)
            missing_field_count += sum(product["missing_count"] for product in shaped_products)

            if analysis_row.get("skip_matching"):
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
                    "serial": boq_row.get("serial", ""),
                    "depth": boq_row.get("depth", 0),
                    "description": description,
                    "qty": _field_from_map(fields, _QTY_KEYS),
                    "unit": _field_from_map(fields, _UNIT_KEYS),
                    "status": status,
                    "product_count": product_total,
                    "products": shaped_products,
                    "activities": activities,
                    "make_list": _shape_make_list(
                        description=description,
                        stored=analysis_row.get("make_list"),
                        make_list_service=self.make_list_service,
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
