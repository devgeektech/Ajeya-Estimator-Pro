"""Make & supplier selection after Analysis — exact Rate_Master match + rates."""
from __future__ import annotations

import logging
import re
from typing import Any

from django.db import transaction

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_store import save_boq_analysis_json
from apps.boq.services.boq_extraction_service import _normalize_product_fields
from apps.boq.services.boq_line_output_service import BOQLineOutputService
from apps.boq.services.labour_detail_retrieval_service import LabourDetailRetrievalService
from apps.boq.services.make_list_constraint_service import MakeListConstraintService
from apps.boq.services.product_matching_service import (
    ProductMatchingService,
    structured_match_score,
)
from apps.boq.services.rate_detail_retrieval_service import RateDetailRetrievalService
from apps.boq.services.serial_normalizer import analysis_fields
from apps.database_manager.models import Rate_Master
from apps.database_manager.services.activation import get_active_database_version
from common.choices import BOQStatus
from common.constants import MATCH_CONFIDENCE_THRESHOLD
from common.exceptions import BOQAIError, ValidationError
from utils.json_safe import json_safe
from utils.timestamps import now_local_iso

logger = logging.getLogger("boq_ai")

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_UNIT_KEYS = ("unit", "uom")


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _field_from_map(fields: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return value
    return None


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


def _ordered_boq_rows(boq_data: dict) -> list[dict[str, Any]]:
    flat_rows = boq_data.get("rows") or []
    return list(flat_rows or [])


class MakeVendorSelectionService:
    """
    After Analysis: expert picks Make + Supplier, then exact Rate_Master search
    using analysis product fields + that make/supplier, then load rates by Tech_Key.
    """

    def __init__(self, boq_id: int, make_list_data: dict | None = None):
        self.boq_id = boq_id
        self.make_list_service = MakeListConstraintService(make_list_data)

    def build_display(self) -> dict[str, Any]:
        boq = self._get_boq()
        analysis = boq.analysis_data or {}
        if not analysis.get("rows"):
            return {"has_products": False, "lines": [], "categories": [], "stats": {}}

        database_version_id = self._database_version_id(boq)
        analysis_by_row = {
            str(row.get("row_id")): row
            for row in analysis.get("rows") or []
            if row.get("row_id")
        }

        lines: list[dict[str, Any]] = []
        selected_count = 0
        matched_count = 0
        product_count = 0

        for boq_row in _ordered_boq_rows(boq.boq_data or {}):
            row_id = str(boq_row.get("row_id") or "")
            analysis_row = analysis_by_row.get(row_id, {})
            if analysis_row.get("skip_reason") == "lineage_child_row":
                continue
            products = list(analysis_row.get("products") or [])
            if not products:
                continue

            fields = analysis_fields(boq_row)
            qty = _field_from_map(fields, _QTY_KEYS)
            unit = _field_from_map(fields, _UNIT_KEYS)
            description = _field_from_map(fields, _DESCRIPTION_KEYS) or ""

            shaped_products = []
            for product in products:
                shaped = self._shape_product(
                    product,
                    row_id=row_id,
                    qty=qty,
                    unit=unit,
                    database_version_id=database_version_id,
                    boq_description=description,
                )
                product_count += 1
                if shaped.get("selected_make") or shaped.get("selected_supplier"):
                    selected_count += 1
                if shaped.get("match_status") == "matched":
                    matched_count += 1
                shaped_products.append(shaped)

            lines.append(
                {
                    "row_id": row_id,
                    "serial": boq_row.get("serial") or "",
                    "depth": boq_row.get("depth") or 0,
                    "description": description,
                    "qty": qty,
                    "unit": unit,
                    "products": shaped_products,
                }
            )

        return {
            "has_products": product_count > 0,
            "database_version_id": database_version_id,
            "stats": {
                "product_count": product_count,
                "selected_count": selected_count,
                "matched_count": matched_count,
            },
            "categories": self._build_category_rows(analysis, database_version_id),
            "lines": lines,
        }

    def apply_category_make(
        self,
        *,
        category: str,
        make: str,
        supplier: str = "",
        find_rates: bool = True,
    ) -> dict[str, Any]:
        """Apply one approved make to every analysed product in ``category``."""
        boq = self._get_boq()
        self._ensure_editable(boq)

        category_text = str(category or "").strip()
        make_text = str(make or "").strip()
        supplier_text = str(supplier or "").strip()
        if not category_text:
            raise ValidationError("Category is required.")
        if not make_text:
            raise ValidationError("Select an approved make for this category.")

        database_version_id = self._database_version_id(boq)
        if find_rates and not database_version_id:
            raise ValidationError("No active master database. Upload a database first.")

        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        boq_by_id = {
            str(row.get("row_id")): row
            for row in _ordered_boq_rows(boq.boq_data or {})
            if row.get("row_id")
        }

        updated_count = 0
        matched_count = 0
        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                continue
            row_id = str(row.get("row_id") or "")
            qty = _field_from_map(analysis_fields(boq_by_id.get(row_id) or {}), _QTY_KEYS)
            changed = False
            for index, product in enumerate(products):
                product_category = str(product.get("category") or "").strip()
                if not product_category:
                    continue
                if _normalize_text(product_category) != _normalize_text(category_text):
                    continue
                updated = dict(product)
                updated["selected_make"] = make_text
                updated["selected_supplier"] = supplier_text or None
                updated["make_hint"] = make_text
                if find_rates:
                    match_payload = self._exact_match_and_rates(
                        updated,
                        make=make_text,
                        supplier=supplier_text,
                        quantity=qty,
                        database_version_id=database_version_id,
                    )
                    updated["vendor_selection"] = match_payload
                    if match_payload.get("status") == "matched":
                        matched_count += 1
                else:
                    selection = dict(updated.get("vendor_selection") or {})
                    selection["make"] = make_text
                    selection["supplier"] = supplier_text
                    selection["status"] = selection.get("status") or "not_searched"
                    updated["vendor_selection"] = selection
                products[index] = updated
                updated_count += 1
                changed = True
            if changed:
                row["products"] = products

        if updated_count == 0:
            raise ValidationError(f"No analysed products found for category '{category_text}'.")

        selections = dict(analysis.get("category_make_selections") or {})
        selections[category_text] = {
            "make": make_text,
            "supplier": supplier_text,
            "applied_at": now_local_iso(),
            "product_count": updated_count,
        }
        analysis["category_make_selections"] = selections
        analysis["rows"] = rows
        if database_version_id:
            analysis["database_version_id"] = database_version_id

        with transaction.atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.info(
            "Category make applied boq=%s category=%s make=%s products=%s matched=%s",
            boq.pk,
            category_text,
            make_text,
            updated_count,
            matched_count,
        )
        return {
            "category": category_text,
            "make": make_text,
            "supplier": supplier_text,
            "updated_count": updated_count,
            "matched_count": matched_count,
        }

    def _build_category_rows(
        self,
        analysis: dict[str, Any],
        database_version_id: int,
    ) -> list[dict[str, Any]]:
        """One row per distinct product category with approved-make options."""
        counts: dict[str, int] = {}
        display_names: dict[str, str] = {}
        for row in analysis.get("rows") or []:
            for product in row.get("products") or []:
                category = str(product.get("category") or "").strip()
                if not category:
                    continue
                key = _normalize_text(category)
                counts[key] = counts.get(key, 0) + 1
                display_names.setdefault(key, category)

        stored = dict(analysis.get("category_make_selections") or {})
        stored_by_norm = {
            _normalize_text(key): {"key": key, **(value or {})}
            for key, value in stored.items()
            if str(key or "").strip()
        }

        categories: list[dict[str, Any]] = []
        for key in sorted(display_names.keys(), key=lambda item: display_names[item].lower()):
            category = display_names[key]
            approved = self.make_list_service.approved_makes_for_category(category) or []
            if not approved:
                approved = self.make_list_service.all_approved_makes()
            # Also include makes already present on Rate_Master for this category.
            if database_version_id:
                for rate in (
                    Rate_Master.objects.filter(
                        database_version_id=database_version_id,
                        Category__iexact=category,
                    )
                    .exclude(Make__isnull=True)
                    .exclude(Make="")
                    .values_list("Make", flat=True)
                    .distinct()[:50]
                ):
                    text = str(rate or "").strip()
                    if text and text not in approved:
                        approved.append(text)

            selection = stored_by_norm.get(key) or {}
            selected_make = str(selection.get("make") or "").strip()
            if selected_make and selected_make not in approved:
                approved = [selected_make] + list(approved)
            categories.append(
                {
                    "category": category,
                    "product_count": counts.get(key, 0),
                    "make_options": approved,
                    "selected_make": selected_make,
                    "selected_supplier": str(selection.get("supplier") or "").strip(),
                }
            )
        return categories

    def select_and_match(
        self,
        *,
        row_id: str,
        product_index: int,
        make: str,
        supplier: str = "",
    ) -> dict[str, Any]:
        """Persist make/supplier, find exact Rate_Master row, load rates via Tech_Key."""
        boq = self._get_boq()
        self._ensure_editable(boq)

        make_text = str(make or "").strip()
        supplier_text = str(supplier or "").strip()
        if not make_text and not supplier_text:
            raise ValidationError("Select a make or supplier before searching.")

        database_version_id = self._database_version_id(boq)
        if not database_version_id:
            raise ValidationError("No active master database. Upload a database first.")

        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        row = next((item for item in rows if str(item.get("row_id")) == str(row_id)), None)
        if row is None:
            raise ValidationError(f"Unknown BOQ row: {row_id}")

        products = list(row.get("products") or [])
        product = next(
            (
                item
                for item in products
                if int(item.get("product_index") or 0) == int(product_index)
            ),
            None,
        )
        if product is None and 0 <= product_index < len(products):
            product = products[product_index]
        if product is None:
            raise ValidationError(f"Unknown product index: {product_index}")

        boq_row = next(
            (
                item
                for item in _ordered_boq_rows(boq.boq_data or {})
                if str(item.get("row_id")) == str(row_id)
            ),
            {},
        )
        qty = _field_from_map(analysis_fields(boq_row), _QTY_KEYS)
        match_payload = self._exact_match_and_rates(
            product,
            make=make_text,
            supplier=supplier_text,
            quantity=qty,
            database_version_id=database_version_id,
        )

        updated = dict(product)
        updated["selected_make"] = make_text or None
        updated["selected_supplier"] = supplier_text or None
        updated["make_hint"] = make_text or updated.get("make_hint")
        updated["vendor_selection"] = match_payload

        position = next(
            (
                index
                for index, item in enumerate(products)
                if int(item.get("product_index") or 0) == int(product_index)
            ),
            product_index if 0 <= product_index < len(products) else None,
        )
        if position is None:
            raise ValidationError(f"Unknown product index: {product_index}")
        products[position] = updated
        row["products"] = products
        analysis["rows"] = rows
        analysis["database_version_id"] = database_version_id

        with transaction.atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.info(
            "Make/vendor selection saved boq=%s row=%s product=%s make=%s supplier=%s status=%s",
            boq.pk,
            row_id,
            product_index,
            make_text,
            supplier_text,
            match_payload.get("status"),
        )
        return match_payload

    def _shape_product(
        self,
        product: dict[str, Any],
        *,
        row_id: str,
        qty: Any,
        unit: Any,
        database_version_id: int,
        boq_description: str,
    ) -> dict[str, Any]:
        product = _normalize_product_fields(product)
        selection = dict(product.get("vendor_selection") or {})
        make_options, supplier_options = self._options_for_product(
            product,
            database_version_id=database_version_id,
            boq_description=boq_description,
        )
        selected_make = product.get("selected_make") or selection.get("make") or ""
        selected_supplier = product.get("selected_supplier") or selection.get("supplier") or ""
        if selected_make and selected_make not in make_options:
            make_options = [selected_make] + make_options
        if selected_supplier and selected_supplier not in supplier_options:
            supplier_options = [selected_supplier] + supplier_options

        rate_detail = selection.get("rate_detail")
        labour_detail = selection.get("labour_detail")
        line_output = selection.get("line_output")
        return {
            "row_id": row_id,
            "product_index": int(product.get("product_index") or 0),
            "summary": _product_summary(product),
            "description_hint": product.get("description_hint") or "",
            "category": product.get("category") or "",
            "sub_category": product.get("sub_category") or "",
            "class": product.get("class") or "",
            "size": product.get("size") if product.get("size") is not None else "",
            "unit": product.get("unit") or "",
            "capacity": product.get("capacity") or "",
            "qty": qty,
            "quantity_unit": product.get("quantity_unit") or unit or "",
            "make_options": make_options,
            "supplier_options": supplier_options,
            "selected_make": selected_make,
            "selected_supplier": selected_supplier,
            "match_status": selection.get("status") or "not_searched",
            "confidence": selection.get("confidence"),
            "tech_key": selection.get("tech_key") or "",
            "rate_master_id": selection.get("rate_master_id"),
            "matched_summary": selection.get("summary") or "",
            "rate_detail": rate_detail,
            "labour_detail": labour_detail,
            "line_output": line_output,
            "notes": selection.get("notes") or "",
        }

    def _options_for_product(
        self,
        product: dict[str, Any],
        *,
        database_version_id: int,
        boq_description: str,
    ) -> tuple[list[str], list[str]]:
        approved = self.make_list_service.make_options_for_product(
            category=str(product.get("category") or ""),
            sub_category=str(product.get("sub_category") or ""),
            description=boq_description or str(product.get("description_hint") or ""),
        )
        preferred_makes = list(approved.get("make_options") or [])
        if not preferred_makes:
            preferred_makes = self.make_list_service.all_approved_makes()

        makes: list[str] = []
        suppliers: list[str] = []
        seen_makes: set[str] = set()
        seen_suppliers: set[str] = set()

        def _add_make(value: Any) -> None:
            text = str(value or "").strip()
            key = _normalize_text(text)
            if not text or key in seen_makes:
                return
            seen_makes.add(key)
            makes.append(text)

        def _add_supplier(value: Any) -> None:
            text = str(value or "").strip()
            key = _normalize_text(text)
            if not text or key in seen_suppliers:
                return
            seen_suppliers.add(key)
            suppliers.append(text)

        for make in preferred_makes:
            _add_make(make)

        if database_version_id:
            matcher = ProductMatchingService(database_version_id)
            for candidate in matcher._sql_fallback_candidates(product)[:50]:
                _add_make(candidate.get("make"))
                _add_supplier(candidate.get("supplier"))
            # Also pull distinct suppliers for preferred makes in this category.
            queryset = Rate_Master.objects.filter(database_version_id=database_version_id)
            category = product.get("category")
            if _is_filled(category):
                queryset = queryset.filter(Category__iexact=str(category).strip())
            for rate in queryset.only("Make", "Supplier")[:200]:
                _add_make(rate.Make)
                _add_supplier(rate.Supplier)

        return makes, suppliers

    def _exact_match_and_rates(
        self,
        product: dict[str, Any],
        *,
        make: str,
        supplier: str,
        quantity: Any,
        database_version_id: int,
    ) -> dict[str, Any]:
        extracted = dict(product)
        if make:
            extracted["make_hint"] = make

        queryset = Rate_Master.objects.filter(database_version_id=database_version_id)
        if make:
            queryset = queryset.filter(Make__iexact=make)
        if supplier:
            queryset = queryset.filter(Supplier__iexact=supplier)

        category = extracted.get("category")
        if _is_filled(category):
            queryset = queryset.filter(Category__iexact=str(category).strip())
        sub_category = extracted.get("sub_category")
        if _is_filled(sub_category):
            # Soft: prefer exact sub_category but do not hard-fail if empty set.
            narrowed = queryset.filter(Sub_Category__iexact=str(sub_category).strip())
            if narrowed.exists():
                queryset = narrowed

        scored: list[tuple[float, Rate_Master, dict[str, Any]]] = []
        for rate in queryset[:80]:
            structured, breakdown = structured_match_score(extracted, rate)
            # Exact make already filtered; boost when supplier also matches.
            if supplier and _normalize_text(rate.Supplier) == _normalize_text(supplier):
                structured = min(100.0, structured + 5.0)
            scored.append((structured, rate, breakdown))

        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return {
                "make": make,
                "supplier": supplier,
                "status": "unmatched",
                "confidence": 0.0,
                "rate_master_id": None,
                "tech_key": "",
                "summary": "",
                "rate_detail": None,
                "labour_detail": None,
                "line_output": BOQLineOutputService.build(
                    quantity=quantity,
                    rate_detail=None,
                    labour_detail=None,
                    is_pending=True,
                ),
                "notes": "No Rate_Master row found for this product with the selected make/supplier.",
                "matched_at": now_local_iso(),
            }

        confidence, rate, breakdown = scored[0]
        rate_service = RateDetailRetrievalService(database_version_id)
        labour_service = LabourDetailRetrievalService(database_version_id)
        rate_detail = rate_service.get_by_id(rate.pk)
        labour_detail = labour_service.get_by_tech_key(
            rate.Tech_Key,
            size=extracted.get("size"),
        )
        status = "matched" if confidence >= MATCH_CONFIDENCE_THRESHOLD else "pending"
        line_output = BOQLineOutputService.build(
            quantity=quantity,
            rate_detail=rate_detail,
            labour_detail=labour_detail,
            is_pending=status != "matched",
        )
        return {
            "make": make or (rate.Make or ""),
            "supplier": supplier or (rate.Supplier or ""),
            "status": status,
            "confidence": round(confidence, 2),
            "rate_master_id": rate.pk,
            "tech_key": rate.Tech_Key or "",
            "summary": _product_summary(
                {
                    "category": rate.Category,
                    "sub_category": rate.Sub_Category,
                    "class": rate.Class,
                    "size": rate.Size,
                    "unit": rate.Unit,
                    "capacity": rate.Capacity,
                }
            )
            + (f" / {rate.Make}" if rate.Make else ""),
            "score_breakdown": breakdown,
            "rate_detail": rate_detail,
            "labour_detail": labour_detail,
            "line_output": line_output,
            "notes": ""
            if status == "matched"
            else "Closest Rate_Master row found — review make/supplier or product fields.",
            "matched_at": now_local_iso(),
        }

    def _database_version_id(self, boq: BOQ) -> int:
        stored = int((boq.analysis_data or {}).get("database_version_id") or 0)
        if stored:
            return stored
        active = get_active_database_version()
        return int(active.pk) if active else 0

    def _get_boq(self) -> BOQ:
        try:
            return BOQ.objects.get(pk=self.boq_id)
        except BOQ.DoesNotExist as exc:
            raise BOQAIError(f"BOQ id={self.boq_id} not found.") from exc

    @staticmethod
    def _ensure_editable(boq: BOQ) -> None:
        if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
            raise ValidationError("Wait for the current job to finish.")
        if not (boq.analysis_data or {}).get("rows"):
            raise ValidationError("Run Analyse first to extract products.")
