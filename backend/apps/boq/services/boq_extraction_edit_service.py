"""Persist user corrections to extracted products on the Analysis tab."""
from __future__ import annotations

import json
import re
from typing import Any

from django.db import transaction

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_store import save_boq_analysis_json
from apps.boq.services.extraction_attribute_fields import COMMON_ATTRIBUTE_KEYS
from apps.boq.services.make_list_constraint_service import MakeListConstraintService, _normalize_make
from common.choices import BOQStatus
from common.exceptions import BOQAIError, ValidationError

PHASE_EXTRACTED = "extracted"

_PRODUCT_SCALAR_FIELDS = (
    "description_hint",
    "category",
    "sub_category",
    "class",
    "size",
    "unit",
    "make_hint",
    "capacity",
    "quantity",
    "quantity_unit",
)

_SIZE_FIELDS = {"size", "capacity"}
_QUANTITY_FIELDS = {"quantity"}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _coerce_scalar(field: str, raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return None
    if field in _SIZE_FIELDS | _QUANTITY_FIELDS:
        try:
            number = float(text)
            return int(number) if number.is_integer() else number
        except ValueError:
            return text
    return text


def _normalize_attributes(raw: dict[str, Any] | None) -> dict[str, str]:
    if not raw:
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        key_text = re.sub(r"\s+", "_", str(key or "").strip().lower())
        if not key_text:
            continue
        value_text = str(value or "").strip()
        if value_text:
            normalized[key_text] = value_text
    return normalized


def _blank_product(product_index: int) -> dict[str, Any]:
    return {
        "product_index": product_index,
        "description_hint": None,
        "category": None,
        "sub_category": None,
        "class": None,
        "size": None,
        "unit": None,
        "make_hint": None,
        "capacity": None,
        "attributes": {},
        "quantity": None,
        "quantity_unit": None,
        "extraction_confidence": 0.0,
        "source": "user",
    }


def _reindex_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reindexed: list[dict[str, Any]] = []
    for index, product in enumerate(products):
        reindexed.append({**product, "product_index": index})
    return reindexed


class BOQExtractionEditService:
    """Update extracted products before matching."""

    def __init__(self, boq_id: int):
        self.boq_id = boq_id

    def update_product(
        self,
        *,
        row_id: str,
        product_index: int,
        fields: dict[str, str],
        attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        boq = self._get_boq()
        self._ensure_editable(boq)

        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        row = self._find_row(rows, row_id)
        if row is None:
            raise ValidationError(f"Unknown BOQ row: {row_id}")

        products = list(row.get("products") or [])
        product = self._find_product(products, product_index)
        if product is None:
            raise ValidationError(f"Unknown product index: {product_index}")

        updated = dict(product)
        for field in _PRODUCT_SCALAR_FIELDS:
            if field not in fields:
                continue
            updated[field] = _coerce_scalar(field, fields[field])

        if attributes is not None:
            updated["attributes"] = _normalize_attributes(attributes)

        position = self._product_position(products, product_index)
        if position is None:
            raise ValidationError(f"Unknown product index: {product_index}")
        products[position] = updated
        row["products"] = products
        row["skip_matching"] = not products
        analysis["rows"] = rows
        analysis["phase"] = PHASE_EXTRACTED
        self._persist(boq, analysis)
        return updated

    def add_product(self, *, row_id: str) -> dict[str, Any]:
        boq = self._get_boq()
        self._ensure_editable(boq)

        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        row = self._find_row(rows, row_id)
        if row is None:
            raise ValidationError(f"Unknown BOQ row: {row_id}")
        if row.get("skip_matching") and not row.get("products"):
            row["skip_matching"] = False

        products = list(row.get("products") or [])
        next_index = len(products)
        product = _blank_product(next_index)
        products.append(product)
        row["products"] = products
        row["skip_matching"] = False
        analysis["rows"] = rows
        self._persist(boq, analysis)
        return product

    def remove_product(self, *, row_id: str, product_index: int) -> None:
        boq = self._get_boq()
        self._ensure_editable(boq)

        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        row = self._find_row(rows, row_id)
        if row is None:
            raise ValidationError(f"Unknown BOQ row: {row_id}")

        products = list(row.get("products") or [])
        position = self._product_position(products, product_index)
        if position is None:
            raise ValidationError(f"Unknown product index: {product_index}")

        products.pop(position)
        row["products"] = _reindex_products(products)
        if not row["products"] and not row.get("activities"):
            row["skip_matching"] = True
        analysis["rows"] = rows
        self._persist(boq, analysis)

    def update_row_make(
        self,
        *,
        row_id: str,
        selected_make: str,
        custom_make: str = "",
        make_list_data: dict | None,
        boq_description: str,
        category: str = "",
        sub_category: str = "",
    ) -> dict[str, Any]:
        boq = self._get_boq()
        self._ensure_editable(boq)

        make_list_service = MakeListConstraintService(make_list_data)
        options = make_list_service.make_options_for_product(
            category=category,
            sub_category=sub_category,
            description=boq_description,
        )
        allowed = list(options.get("make_options") or [])

        if selected_make == "__custom__":
            normalized_make = _normalize_make(custom_make)
            if not normalized_make:
                raise ValidationError("Enter a custom make.")
            is_custom = True
        else:
            normalized_make = _normalize_make(selected_make)
            if not normalized_make:
                raise ValidationError("Select a make from the list or choose Other.")
            is_custom = bool(allowed) and normalized_make not in allowed
            if allowed and not is_custom and normalized_make not in allowed:
                raise ValidationError("Selected make is not available for this category.")

        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        row = self._find_row(rows, row_id)
        if row is None:
            raise ValidationError(f"Unknown BOQ row: {row_id}")

        row["make_list"] = {
            "material": options.get("material") or options.get("category_material") or "",
            "approved_makes": allowed,
            "selected_make": normalized_make,
            "custom_make": normalized_make if is_custom else "",
            "custom_make_flag": is_custom,
            "match_score": options.get("match_score"),
            "category_material": options.get("category_material") or "",
        }
        analysis["rows"] = rows
        analysis["phase"] = PHASE_EXTRACTED
        self._persist(boq, analysis)
        return row["make_list"]

    def parse_attributes_from_form(self, post_data) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for key in COMMON_ATTRIBUTE_KEYS:
            value = (post_data.get(f"attr_{key}") or "").strip()
            if value:
                attrs[key] = value

        extra_keys = post_data.getlist("extra_attr_key")
        extra_values = post_data.getlist("extra_attr_value")
        for raw_key, raw_value in zip(extra_keys, extra_values, strict=False):
            key = re.sub(r"\s+", "_", str(raw_key or "").strip().lower())
            value = str(raw_value or "").strip()
            if key and value:
                attrs[key] = value
        return _normalize_attributes(attrs)

    def parse_attributes_json(self, raw: str) -> dict[str, str]:
        text = (raw or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError("Attributes must be valid JSON object.") from exc
        if not isinstance(payload, dict):
            raise ValidationError("Attributes must be a JSON object.")
        return _normalize_attributes(payload)

    @staticmethod
    def _find_row(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any] | None:
        for row in rows:
            if str(row.get("row_id")) == str(row_id):
                return row
        return None

    @staticmethod
    def _find_product(products: list[dict[str, Any]], product_index: int) -> dict[str, Any] | None:
        position = BOQExtractionEditService._product_position(products, product_index)
        if position is None:
            return None
        return products[position]

    @staticmethod
    def _product_position(products: list[dict[str, Any]], product_index: int) -> int | None:
        for position, product in enumerate(products):
            if int(product.get("product_index") or 0) == product_index:
                return position
        if 0 <= product_index < len(products):
            return product_index
        return None

    def _get_boq(self) -> BOQ:
        try:
            return BOQ.objects.get(pk=self.boq_id)
        except BOQ.DoesNotExist:
            raise BOQAIError(f"BOQ id={self.boq_id} not found.") from None

    @staticmethod
    def _ensure_editable(boq: BOQ) -> None:
        if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
            raise ValidationError("Wait for the current job to finish before editing.")
        if not (boq.analysis_data or {}).get("rows"):
            raise ValidationError("Run Analyse first to extract products.")

    def _persist(self, boq: BOQ, analysis: dict[str, Any]) -> None:
        stats = dict((analysis.get("stats") or {}))
        products_total = 0
        activities_total = 0
        rows_skipped = 0
        for row in analysis.get("rows") or []:
            if row.get("skip_matching"):
                rows_skipped += 1
            products_total += len(row.get("products") or [])
            activities_total += len(row.get("activities") or [])
        stats.update(
            {
                "products_total": products_total,
                "activities_total": activities_total,
                "rows_skipped": rows_skipped,
            }
        )
        analysis["stats"] = stats
        analysis["phase"] = PHASE_EXTRACTED
        for row in analysis.get("rows") or []:
            row.pop("product_matches", None)

        with transaction.atomic():
            save_boq_analysis_json(boq.boq_name, analysis)
            boq.analysis_data = analysis
            if boq.status == BOQStatus.PROCESSED:
                boq.status = BOQStatus.EXTRACTED
            boq.save(update_fields=["analysis_data", "status"])
