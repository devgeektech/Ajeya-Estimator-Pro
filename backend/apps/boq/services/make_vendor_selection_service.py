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
from apps.boq.services.make_list_constraint_service import (
    LOWEST_MAKE_LABEL,
    LOWEST_MAKE_STORED,
    LOWEST_MAKE_VALUE,
    MakeListConstraintService,
)
from apps.boq.services.product_matching_service import (
    ProductMatchingService,
    structured_match_score,
)
from apps.boq.services.rate_detail_retrieval_service import RateDetailRetrievalService
from ai.embeddings.chroma_store import selection_amount
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
_SUBCATEGORY_SEP = "::"


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


def _taxonomy_label(product: dict[str, Any]) -> str:
    category = str(product.get("category") or "").strip()
    sub_category = str(product.get("sub_category") or "").strip()
    if category and sub_category:
        return f"{category} / {sub_category}"
    return category or sub_category or "—"


def _subcategory_storage_key(category: str, sub_category: str) -> str:
    return f"{str(category or '').strip()}{_SUBCATEGORY_SEP}{str(sub_category or '').strip()}"


def _product_matches_subcategory(
    product: dict[str, Any],
    *,
    category: str,
    sub_category: str,
) -> bool:
    product_category = str(product.get("category") or "").strip()
    if not product_category:
        return False
    if _normalize_text(product_category) != _normalize_text(category):
        return False
    product_sub = str(product.get("sub_category") or "").strip()
    return _normalize_text(product_sub) == _normalize_text(sub_category)


def _is_lowest_make(value: str) -> bool:
    return MakeListConstraintService.is_lowest_make_selection(value)


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
            "selection_catalog": self._build_selection_catalog(analysis, database_version_id),
            "lines": lines,
        }

    def apply_subcategory_make(
        self,
        *,
        category: str,
        sub_category: str,
        make: str = "",
        supplier: str = "",
        find_rates: bool = True,
        prefer_lowest_price: bool | None = None,
    ) -> dict[str, Any]:
        """Apply make/supplier to every analysed product in category + sub-category."""
        boq = self._get_boq()
        self._ensure_editable(boq)

        category_text = str(category or "").strip()
        sub_category_text = str(sub_category or "").strip()
        make_text = str(make or "").strip()
        supplier_text = str(supplier or "").strip()
        if not category_text:
            raise ValidationError("Category is required.")
        if not sub_category_text:
            raise ValidationError("Sub-category is required.")

        approved_makes = self.make_list_service.approved_makes_for_category(
            category_text,
            sub_category_text,
        ) or []
        if not approved_makes:
            approved_makes = self.make_list_service.all_approved_makes()

        use_lowest = prefer_lowest_price
        if use_lowest is None:
            use_lowest = (not make_text) or _is_lowest_make(make_text)
        if use_lowest:
            make_text = ""
        elif make_text and not MakeListConstraintService.make_is_allowed(make_text, approved_makes or None):
            raise ValidationError(
                f"Make '{make_text}' is not in the approved make list for this sub-category."
            )

        if supplier_text and _is_lowest_make(supplier_text):
            supplier_text = ""

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
        applied_make = make_text
        applied_supplier = supplier_text
        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                continue
            row_id = str(row.get("row_id") or "")
            qty = _field_from_map(analysis_fields(boq_by_id.get(row_id) or {}), _QTY_KEYS)
            changed = False
            for index, product in enumerate(products):
                if not _product_matches_subcategory(
                    product,
                    category=category_text,
                    sub_category=sub_category_text,
                ):
                    continue
                updated = dict(product)
                match_payload: dict[str, Any] | None = None
                if find_rates:
                    match_payload = self._exact_match_and_rates(
                        updated,
                        make=make_text,
                        supplier=supplier_text,
                        quantity=qty,
                        database_version_id=database_version_id,
                        prefer_lowest_price=use_lowest
                        or (bool(make_text) and not supplier_text),
                        approved_makes=approved_makes or None,
                    )
                    updated["vendor_selection"] = match_payload
                    applied_make = match_payload.get("make") or applied_make
                    applied_supplier = match_payload.get("supplier") or applied_supplier
                    if match_payload.get("status") == "matched":
                        matched_count += 1
                else:
                    selection = dict(updated.get("vendor_selection") or {})
                    selection["make"] = make_text
                    selection["supplier"] = supplier_text
                    selection["status"] = selection.get("status") or "not_searched"
                    updated["vendor_selection"] = selection
                updated["selected_make"] = applied_make or None
                updated["selected_supplier"] = applied_supplier or None
                if applied_make:
                    updated["make_hint"] = applied_make
                products[index] = updated
                updated_count += 1
                changed = True
            if changed:
                row["products"] = products

        if updated_count == 0:
            label = f"{category_text} / {sub_category_text}"
            raise ValidationError(f"No analysed products found for sub-category '{label}'.")

        storage_key = _subcategory_storage_key(category_text, sub_category_text)
        selections = dict(analysis.get("subcategory_make_selections") or {})
        selections[storage_key] = {
            "category": category_text,
            "sub_category": sub_category_text,
            "make": applied_make,
            "supplier": applied_supplier,
            "prefer_lowest_price": use_lowest,
            "applied_at": now_local_iso(),
            "product_count": updated_count,
            "source": "manual",
        }
        analysis["subcategory_make_selections"] = selections
        analysis["rows"] = rows
        if database_version_id:
            analysis["database_version_id"] = database_version_id

        with transaction.atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.info(
            "Sub-category make applied boq=%s category=%s sub_category=%s make=%s supplier=%s products=%s matched=%s",
            boq.pk,
            category_text,
            sub_category_text,
            applied_make,
            applied_supplier,
            updated_count,
            matched_count,
        )
        return {
            "category": category_text,
            "sub_category": sub_category_text,
            "make": applied_make,
            "supplier": applied_supplier,
            "prefer_lowest_price": use_lowest,
            "updated_count": updated_count,
            "matched_count": matched_count,
        }

    def apply_lowest_defaults_all(self, *, find_rates: bool = True) -> dict[str, Any]:
        """
        Prefill every analysed product with lowest-price Rate_Master row among
        approved makes for its category / sub-category (Next from Analysis).
        """
        boq = self._get_boq()
        self._ensure_editable(boq)

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
        selections = dict(analysis.get("subcategory_make_selections") or {})
        pair_stats: dict[str, dict[str, Any]] = {}

        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                continue
            row_id = str(row.get("row_id") or "")
            qty = _field_from_map(analysis_fields(boq_by_id.get(row_id) or {}), _QTY_KEYS)
            changed = False
            for index, product in enumerate(products):
                category_text = str(product.get("category") or "").strip()
                sub_category_text = str(product.get("sub_category") or "").strip() or "—"
                if not category_text:
                    continue
                approved_makes = self._approved_makes_for_subcategory(
                    category_text,
                    sub_category_text,
                )
                match_payload = self._exact_match_and_rates(
                    product,
                    make="",
                    supplier="",
                    quantity=qty,
                    database_version_id=database_version_id,
                    prefer_lowest_price=True,
                    approved_makes=approved_makes or None,
                )
                updated = dict(product)
                updated["vendor_selection"] = match_payload
                applied_make = match_payload.get("make") or ""
                applied_supplier = match_payload.get("supplier") or ""
                updated["selected_make"] = applied_make or None
                updated["selected_supplier"] = applied_supplier or None
                if applied_make:
                    updated["make_hint"] = applied_make
                products[index] = updated
                updated_count += 1
                changed = True
                if match_payload.get("status") == "matched":
                    matched_count += 1

                storage_key = _subcategory_storage_key(category_text, sub_category_text)
                stats = pair_stats.setdefault(
                    storage_key,
                    {
                        "category": category_text,
                        "sub_category": sub_category_text,
                        "make": applied_make,
                        "supplier": applied_supplier,
                        "prefer_lowest_price": True,
                        "product_count": 0,
                    },
                )
                stats["product_count"] += 1
                if applied_make:
                    stats["make"] = applied_make
                if applied_supplier:
                    stats["supplier"] = applied_supplier
            if changed:
                row["products"] = products

        if updated_count == 0:
            raise ValidationError("No analysed products to prefill with make/vendor.")

        applied_at = now_local_iso()
        for key, stats in pair_stats.items():
            selections[key] = {
                **stats,
                "applied_at": applied_at,
                "source": "lowest_defaults",
            }
        analysis["subcategory_make_selections"] = selections
        analysis["rows"] = rows
        if database_version_id:
            analysis["database_version_id"] = database_version_id

        with transaction.atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.info(
            "Lowest make/vendor defaults applied boq=%s products=%s matched=%s pairs=%s",
            boq.pk,
            updated_count,
            matched_count,
            len(pair_stats),
        )
        return {
            "updated_count": updated_count,
            "matched_count": matched_count,
            "pair_count": len(pair_stats),
            "selections": list(pair_stats.values()),
        }

    def apply_category_make(
        self,
        *,
        category: str,
        make: str,
        supplier: str = "",
        find_rates: bool = True,
    ) -> dict[str, Any]:
        """Backward-compatible wrapper — applies to the first sub-category in category."""
        boq = self._get_boq()
        analysis = boq.analysis_data or {}
        catalog = self._collect_extraction_catalog(analysis)
        sub_categories = catalog.get("sub_categories_by_category", {}).get(
            _normalize_text(category),
            [],
        )
        if not sub_categories:
            raise ValidationError(f"No analysed products found for category '{category}'.")
        sub_category = sub_categories[0]["sub_category"]
        return self.apply_subcategory_make(
            category=category,
            sub_category=sub_category,
            make=make,
            supplier=supplier,
            find_rates=find_rates,
        )

    def _collect_extraction_catalog(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """Categories and sub-categories present on analysed products only."""
        category_counts: dict[str, int] = {}
        category_names: dict[str, str] = {}
        sub_counts: dict[str, dict[str, int]] = {}
        sub_names: dict[str, dict[str, str]] = {}

        for row in analysis.get("rows") or []:
            for product in row.get("products") or []:
                category = str(product.get("category") or "").strip()
                if not category:
                    continue
                cat_key = _normalize_text(category)
                category_counts[cat_key] = category_counts.get(cat_key, 0) + 1
                category_names.setdefault(cat_key, category)

                sub_category = str(product.get("sub_category") or "").strip() or "—"
                sub_key = _normalize_text(sub_category)
                sub_counts.setdefault(cat_key, {})
                sub_names.setdefault(cat_key, {})
                sub_counts[cat_key][sub_key] = sub_counts[cat_key].get(sub_key, 0) + 1
                sub_names[cat_key].setdefault(sub_key, sub_category)

        sub_categories_by_category: dict[str, list[dict[str, Any]]] = {}
        for cat_key, subs in sub_counts.items():
            items: list[dict[str, Any]] = []
            for sub_key, count in subs.items():
                items.append(
                    {
                        "sub_category": sub_names[cat_key][sub_key],
                        "product_count": count,
                    }
                )
            items.sort(key=lambda item: str(item["sub_category"]).lower())
            sub_categories_by_category[cat_key] = items

        categories = [
            {
                "category": category_names[key],
                "product_count": category_counts[key],
            }
            for key in sorted(category_names.keys(), key=lambda item: category_names[item].lower())
        ]
        return {
            "categories": categories,
            "sub_categories_by_category": sub_categories_by_category,
        }

    def _approved_makes_for_subcategory(self, category: str, sub_category: str) -> list[str]:
        """Approved makes from make list — primary source of truth."""
        approved = self.make_list_service.approved_makes_for_category(category, sub_category) or []
        if approved:
            return list(approved)
        return self.make_list_service.all_approved_makes()

    def _suppliers_for_subcategory_make(
        self,
        *,
        database_version_id: int,
        category: str,
        sub_category: str,
        make: str,
    ) -> list[str]:
        if not database_version_id or not make or _is_lowest_make(make):
            return []
        queryset = Rate_Master.objects.filter(
            database_version_id=database_version_id,
            Category__iexact=str(category).strip(),
            Make__iexact=str(make).strip(),
        )
        if str(sub_category or "").strip() and sub_category != "—":
            narrowed = queryset.filter(Sub_Category__iexact=str(sub_category).strip())
            if narrowed.exists():
                queryset = narrowed
        suppliers: list[str] = []
        seen: set[str] = set()
        for supplier in queryset.exclude(Supplier__isnull=True).exclude(Supplier="").values_list(
            "Supplier", flat=True
        ).distinct()[:100]:
            text = str(supplier or "").strip()
            key = _normalize_text(text)
            if text and key not in seen:
                seen.add(key)
                suppliers.append(text)
        return sorted(suppliers, key=lambda item: item.lower())

    def _build_selection_catalog(
        self,
        analysis: dict[str, Any],
        database_version_id: int,
    ) -> dict[str, Any]:
        """Cascade data for Make & Vendor: category → sub-category → make → supplier."""
        catalog = self._collect_extraction_catalog(analysis)
        stored = dict(analysis.get("subcategory_make_selections") or {})

        categories_out: list[dict[str, Any]] = []
        for category_row in catalog["categories"]:
            category = category_row["category"]
            cat_key = _normalize_text(category)
            sub_rows: list[dict[str, Any]] = []
            for sub_row in catalog["sub_categories_by_category"].get(cat_key, []):
                sub_category = sub_row["sub_category"]
                storage_key = _subcategory_storage_key(category, sub_category)
                selection = stored.get(storage_key) or {}
                approved = self._approved_makes_for_subcategory(category, sub_category)
                make_options = [LOWEST_MAKE_LABEL] + list(approved)
                selected_make = str(selection.get("make") or "").strip()
                if selection.get("prefer_lowest_price") and not selected_make:
                    selected_make = LOWEST_MAKE_LABEL
                elif selected_make and selected_make not in make_options:
                    make_options = [selected_make] + make_options

                suppliers_by_make: dict[str, list[str]] = {}
                for make_option in approved:
                    suppliers_by_make[make_option] = self._suppliers_for_subcategory_make(
                        database_version_id=database_version_id,
                        category=category,
                        sub_category=sub_category,
                        make=make_option,
                    )

                selected_supplier = str(selection.get("supplier") or "").strip()
                supplier_options: list[str] = []
                if selected_make and not _is_lowest_make(selected_make):
                    supplier_options = list(suppliers_by_make.get(selected_make) or [])
                if supplier_options:
                    supplier_options = [
                        item for item in supplier_options if not _is_lowest_make(item)
                    ]

                sub_rows.append(
                    {
                        "sub_category": sub_category,
                        "product_count": sub_row["product_count"],
                        "make_options": make_options,
                        "suppliers_by_make": suppliers_by_make,
                        "supplier_options": supplier_options,
                        "selected_make": selected_make,
                        "selected_supplier": selected_supplier,
                        "prefer_lowest_price": bool(selection.get("prefer_lowest_price")),
                    }
                )
            categories_out.append(
                {
                    "category": category,
                    "product_count": category_row["product_count"],
                    "sub_categories": sub_rows,
                }
            )

        applied_filters: list[dict[str, Any]] = []
        for key, value in stored.items():
            if not isinstance(value, dict):
                continue
            category = str(value.get("category") or "").strip()
            sub_category = str(value.get("sub_category") or "").strip()
            if not category and _SUBCATEGORY_SEP in str(key):
                category, sub_category = str(key).split(_SUBCATEGORY_SEP, 1)
            applied_filters.append(
                {
                    "category": category,
                    "sub_category": sub_category,
                    "make": str(value.get("make") or "").strip() or "Lowest price",
                    "supplier": str(value.get("supplier") or "").strip() or "Auto (lowest price)",
                    "prefer_lowest_price": bool(value.get("prefer_lowest_price")),
                    "product_count": int(value.get("product_count") or 0),
                    "source": str(value.get("source") or "").strip(),
                }
            )
        applied_filters.sort(
            key=lambda item: (
                str(item.get("category") or "").lower(),
                str(item.get("sub_category") or "").lower(),
            )
        )
        return {"categories": categories_out, "applied_filters": applied_filters}

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

        category = str(product.get("category") or "").strip()
        sub_category = str(product.get("sub_category") or "").strip()
        approved_makes = self._approved_makes_for_subcategory(category, sub_category) or None
        prefer_lowest = _is_lowest_make(make_text) or (not make_text and not supplier_text)
        if make_text and not _is_lowest_make(make_text) and approved_makes:
            if not MakeListConstraintService.make_is_allowed(make_text, approved_makes):
                raise ValidationError(
                    f"Make '{make_text}' is not approved for {category} / {sub_category}."
                )
        if _is_lowest_make(supplier_text):
            supplier_text = ""
        if prefer_lowest:
            make_text = ""

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
            prefer_lowest_price=prefer_lowest or (bool(make_text) and not supplier_text),
            approved_makes=approved_makes,
        )

        updated = dict(product)
        updated["selected_make"] = match_payload.get("make") or make_text or None
        updated["selected_supplier"] = match_payload.get("supplier") or supplier_text or None
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
            "taxonomy_label": _taxonomy_label(product),
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
        category = str(product.get("category") or "")
        sub_category = str(product.get("sub_category") or "")
        approved = self._approved_makes_for_subcategory(category, sub_category)
        preferred_makes = [LOWEST_MAKE_LABEL] + list(approved)

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

        selected_make = str(product.get("selected_make") or "").strip()
        if selected_make and not _is_lowest_make(selected_make):
            for supplier in self._suppliers_for_subcategory_make(
                database_version_id=database_version_id,
                category=category,
                sub_category=sub_category,
                make=selected_make,
            ):
                _add_supplier(supplier)

        if database_version_id and selected_make and not _is_lowest_make(selected_make):
            matcher = ProductMatchingService(database_version_id)
            for candidate in matcher._sql_fallback_candidates(product)[:30]:
                if _normalize_text(candidate.get("make") or "") == _normalize_text(selected_make):
                    _add_supplier(candidate.get("supplier"))

        if suppliers:
            suppliers = [item for item in suppliers if not _is_lowest_make(item)]

        return makes, suppliers

    def _exact_match_and_rates(
        self,
        product: dict[str, Any],
        *,
        make: str,
        supplier: str,
        quantity: Any,
        database_version_id: int,
        prefer_lowest_price: bool = False,
        approved_makes: list[str] | None = None,
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
            narrowed = queryset.filter(Sub_Category__iexact=str(sub_category).strip())
            if narrowed.exists():
                queryset = narrowed

        rate_rows = list(queryset[:120])
        if approved_makes:
            rate_rows = MakeListConstraintService.filter_rate_ids_by_make(rate_rows, approved_makes)
        elif prefer_lowest_price:
            approved = self._approved_makes_for_subcategory(
                str(category or ""),
                str(sub_category or ""),
            )
            if approved:
                rate_rows = MakeListConstraintService.filter_rate_ids_by_make(rate_rows, approved)

        scored: list[tuple[float, Rate_Master, dict[str, Any], float]] = []
        for rate in rate_rows:
            structured, breakdown = structured_match_score(extracted, rate)
            if supplier and _normalize_text(rate.Supplier) == _normalize_text(supplier):
                structured = min(100.0, structured + 5.0)
            amount = float(selection_amount(rate))
            scored.append((structured, rate, breakdown, amount))

        if prefer_lowest_price and scored:
            scored.sort(
                key=lambda item: (
                    item[3],
                    -item[0],
                )
            )
        else:
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

        confidence, rate, breakdown, _amount = scored[0]
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
            "prefer_lowest_price": prefer_lowest_price,
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
