"""Cascade Apply / lowest-defaults / selection catalog for Make & Vendor."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from common.db import atomic

from apps.boq.services.boq_analysis_store import save_boq_analysis_json
from apps.boq.services.boq_line_output_service import BOQLineOutputService
from apps.boq.services.boq_row_fields import (
    QTY_KEYS as _QTY_KEYS,
    field_from_map as _field_from_map,
    normalize_text as _normalize_text,
    ordered_boq_rows as _ordered_boq_rows,
)
from apps.boq.services.make_list_constraint_service import (
    LOWEST_MAKE_LABEL,
    NO_APPROVED_MAKE_LABEL,
    MakeListConstraintService,
)
from apps.boq.services.make_vendor_common import (
    NOT_AVAILABLE_NOTES,
    NOT_AVAILABLE_SOURCE,
    NOT_AVAILABLE_STATUS,
    _SUBCATEGORY_SEP,
    _catalog_product_id,
    _is_lowest_make,
    _product_matches_subcategory,
    _subcategory_storage_key,
    count_missing_loaded_product_ids,
    loaded_catalog_product_id,
)
from apps.boq.services.product_availability import (
    REASON_NO_PRODUCT_ID,
    mark_product_not_available,
)
from apps.boq.services.serial_normalizer import analysis_fields
from common.choices import BOQStatus
from common.exceptions import ValidationError
from utils.json_safe import json_safe
from utils.timestamps import now_local_iso

if TYPE_CHECKING:
    from apps.boq.models import BOQ

logger = logging.getLogger("boq_ai")


class MakeVendorCascadeMixin:
    """Category / sub-category cascade apply and selection catalog."""

    # Provided by MakeVendorSelectionService / sibling mixins (TYPE_CHECKING only —
    # must not define runtime stubs that would shadow RatesMixin via MRO).
    if TYPE_CHECKING:
        make_list_service: MakeListConstraintService
        has_make_list: bool

        def _get_boq(self) -> BOQ: ...
        def _ensure_editable(self, boq: BOQ) -> None: ...
        def _database_version_id(self, boq: BOQ) -> int: ...
        def build_display(self) -> dict[str, Any]: ...
        def _approved_makes_for_subcategory(
            self, category: str, sub_category: str
        ) -> list[str]: ...
        def _exact_match_and_rates(
            self,
            product: dict[str, Any],
            *,
            make: str,
            vendor: str,
            quantity: Any,
            database_version_id: int,
            prefer_lowest_price: bool = False,
            approved_makes: list[str] | None = None,
        ) -> dict[str, Any]: ...
        def _capture_analysis_product_id(
            self,
            product: dict[str, Any],
            *,
            database_version_id: int,
        ) -> tuple[dict[str, Any], str]: ...
        def _ensure_catalog_product_id(
            self,
            product: dict[str, Any],
            *,
            database_version_id: int,
        ) -> dict[str, Any]: ...
        def _make_options_for_scope(
            self,
            *,
            database_version_id: int,
            category: str,
            sub_category: str,
        ) -> tuple[list[str], list[str], bool]: ...
        def _vendors_for_subcategory_make(
            self,
            *,
            database_version_id: int,
            category: str,
            sub_category: str,
            make: str,
        ) -> list[str]: ...
        def _lowest_amount_maps(
            self,
            *,
            database_version_id: int,
            category: str,
            sub_category: str,
            approved_makes: list[str] | None,
        ) -> dict[str, Any]: ...

    def apply_subcategory_make(
        self,
        *,
        category: str,
        sub_category: str,
        make: str = "",
        vendor: str = "",
        find_rates: bool = True,
        prefer_lowest_price: bool | None = None,
    ) -> dict[str, Any]:
        """Apply make/vendor to every analysed product in category + sub-category."""
        boq = self._get_boq()
        self._ensure_editable(boq)

        category_text = str(category or "").strip()
        sub_category_text = str(sub_category or "").strip()
        make_text = str(make or "").strip()
        vendor_text = str(vendor or "").strip()
        if not category_text:
            raise ValidationError("Category is required.")
        # Sub-category may be blank to apply make/vendor across the whole category.

        approved_makes = self.make_list_service.approved_makes_for_category(
            category_text,
            sub_category_text,
        ) or []
        # With a make list: do not fall back to every make when this scope has none.
        # With no make list: allow lowest price across all Rate_Master_Output makes.

        use_lowest = prefer_lowest_price
        if use_lowest is None:
            use_lowest = (not make_text) or _is_lowest_make(make_text)
        if use_lowest:
            make_text = ""
        elif (
            self.has_make_list
            and make_text
            and not MakeListConstraintService.make_is_allowed(
                make_text, approved_makes or None
            )
        ):
            scope = (
                f"{category_text} / {sub_category_text}"
                if sub_category_text
                else category_text
            )
            raise ValidationError(
                f"Make '{make_text}' is not in the approved make list for {scope}."
            )

        if (
            self.has_make_list
            and not approved_makes
            and (use_lowest or not make_text)
        ):
            scope = (
                f"{category_text} / {sub_category_text}"
                if sub_category_text
                else category_text
            )
            raise ValidationError(
                f"{NO_APPROVED_MAKE_LABEL} for {scope}. Enter a make to continue."
            )

        if vendor_text and _is_lowest_make(vendor_text):
            vendor_text = ""

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
        applied_vendor = vendor_text
        applied_amount: float | None = None
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
                        vendor=vendor_text,
                        quantity=qty,
                        database_version_id=database_version_id,
                        prefer_lowest_price=use_lowest
                        or (bool(make_text) and not vendor_text),
                        approved_makes=approved_makes or None,
                    )
                    updated["vendor_selection"] = match_payload
                    applied_make = match_payload.get("make") or applied_make
                    applied_vendor = match_payload.get("vendor") or applied_vendor
                    if match_payload.get("status") == "matched":
                        matched_count += 1
                    rate_text = str(
                        (match_payload.get("line_output") or {}).get("material_rate")
                        or ""
                    ).strip()
                    try:
                        rate_number = float(rate_text.replace(",", ""))
                    except (TypeError, ValueError):
                        rate_number = None
                    if rate_number is not None and (
                        applied_amount is None or rate_number < applied_amount
                    ):
                        applied_amount = rate_number
                else:
                    selection = dict(updated.get("vendor_selection") or {})
                    selection["make"] = make_text
                    selection["vendor"] = vendor_text
                    selection["status"] = selection.get("status") or "not_searched"
                    updated["vendor_selection"] = selection
                updated["selected_make"] = applied_make or None
                updated["selected_vendor"] = applied_vendor or None
                if applied_make:
                    updated["make_hint"] = applied_make
                updated["approved_make_found"] = True
                updated["vendor_selection_source"] = "manual"
                products[index] = updated
                updated_count += 1
                changed = True
            if changed:
                row["products"] = products

        if updated_count == 0:
            label = (
                f"{category_text} / {sub_category_text}"
                if sub_category_text
                else category_text
            )
            raise ValidationError(f"No analysed products found for '{label}'.")

        storage_key = _subcategory_storage_key(category_text, sub_category_text)
        selections = dict(analysis.get("subcategory_make_selections") or {})
        selections[storage_key] = {
            "category": category_text,
            "sub_category": sub_category_text,
            "make": applied_make,
            "vendor": applied_vendor,
            "amount": (
                f"{applied_amount:.2f}" if applied_amount is not None else ""
            ),
            "prefer_lowest_price": use_lowest,
            "applied_at": now_local_iso(),
            "product_count": updated_count,
            "source": "manual",
        }
        analysis["subcategory_make_selections"] = selections
        analysis["rows"] = rows
        if database_version_id:
            analysis["database_version_id"] = database_version_id

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.debug(
            "Sub-category make applied boq=%s category=%s sub_category=%s make=%s vendor=%s products=%s matched=%s",
            boq.pk,
            category_text,
            sub_category_text,
            applied_make,
            applied_vendor,
            updated_count,
            matched_count,
        )
        return {
            "category": category_text,
            "sub_category": sub_category_text,
            "make": applied_make,
            "vendor": applied_vendor,
            "amount": (
                f"{applied_amount:.2f}" if applied_amount is not None else ""
            ),
            "prefer_lowest_price": use_lowest,
            "updated_count": updated_count,
            "matched_count": matched_count,
        }


    def _restore_product_to_lowest(
        self,
        product: dict[str, Any],
        *,
        qty: Any,
        database_version_id: int,
        open_lowest: bool,
    ) -> dict[str, Any]:
        """Reload the lowest-price Rate_Master make/vendor for one product."""
        updated = dict(product)
        category_for_product = str(updated.get("category") or "").strip()
        sub_for_product = str(updated.get("sub_category") or "").strip()
        approved_makes = self._approved_makes_for_subcategory(
            category_for_product,
            sub_for_product,
        )
        # Prefer approved-make lowest when the make list has them; otherwise use
        # Product_ID Rate_Master rows so the product rate still comes back.
        constrain = bool(approved_makes) and not open_lowest
        match_payload = self._exact_match_and_rates(
            updated,
            make="",
            vendor="",
            quantity=qty,
            database_version_id=database_version_id,
            prefer_lowest_price=True,
            approved_makes=approved_makes if constrain else None,
        )
        matched = match_payload.get("status") == "matched"
        if matched:
            source_out = "lowest_defaults"
            approved_found = True
        elif self.has_make_list and not approved_makes:
            source_out = "not_found"
            approved_found = False
            if not match_payload.get("notes"):
                match_payload["notes"] = NO_APPROVED_MAKE_LABEL
        else:
            source_out = "lowest_defaults"
            approved_found = True if open_lowest else bool(approved_makes)

        updated["vendor_selection"] = match_payload
        applied_make = str(match_payload.get("make") or "").strip()
        applied_vendor = str(match_payload.get("vendor") or "").strip()
        updated["selected_make"] = applied_make or None
        updated["selected_vendor"] = applied_vendor or None
        if applied_make:
            updated["make_hint"] = applied_make
        updated["approved_make_found"] = approved_found
        updated["vendor_selection_source"] = source_out
        return updated

    def _has_remaining_specific_filter(
        self,
        *,
        category: str,
        sub_category: str,
        remaining: dict[str, Any],
    ) -> bool:
        """True when a more specific manual filter still covers this sub-category."""
        if not sub_category:
            return False
        specific = remaining.get(_subcategory_storage_key(category, sub_category)) or {}
        if str(specific.get("source") or "").strip() == "manual":
            return True
        return any(
            isinstance(value, dict)
            and str(value.get("source") or "").strip() == "manual"
            and _normalize_text(value.get("category")) == _normalize_text(category)
            and _normalize_text(value.get("sub_category")) == _normalize_text(sub_category)
            for value in remaining.values()
        )

    def _restore_scope_to_lowest(
        self,
        rows: list[dict[str, Any]],
        *,
        category: str,
        sub_category: str,
        remaining: dict[str, Any],
        database_version_id: int,
        boq_by_id: dict[str, Any],
        open_lowest: bool,
    ) -> int:
        """Restore cascade-applied products in one category/sub to lowest price."""
        cleared = 0
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
                    category=category,
                    sub_category=sub_category,
                ):
                    continue
                product_sub = str(product.get("sub_category") or "").strip()
                if not sub_category and self._has_remaining_specific_filter(
                    category=category,
                    sub_category=product_sub,
                    remaining=remaining,
                ):
                    continue
                if str(product.get("vendor_selection_source") or "").strip() != "manual":
                    continue
                products[index] = self._restore_product_to_lowest(
                    product,
                    qty=qty,
                    database_version_id=database_version_id,
                    open_lowest=open_lowest,
                )
                cleared += 1
                changed = True
            if changed:
                row["products"] = products
        return cleared

    def _persist_filter_restore(
        self,
        boq: Any,
        analysis: dict[str, Any],
        *,
        rows: list[dict[str, Any]],
        selections: dict[str, Any],
        database_version_id: int,
    ) -> dict[str, Any]:
        analysis["subcategory_make_selections"] = selections
        analysis["rows"] = rows
        if database_version_id:
            analysis["database_version_id"] = database_version_id
        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])
        return self.build_display().get("stats") or {}

    def remove_subcategory_filter(
        self,
        *,
        category: str,
        sub_category: str = "",
    ) -> dict[str, Any]:
        """Remove a manual cascade filter and restore those products to the same
        lowest-price Make & Vendor state as the initial Make & Vendor load.
        """
        boq = self._get_boq()
        self._ensure_editable(boq)

        category_text = str(category or "").strip()
        sub_category_text = str(sub_category or "").strip()
        if sub_category_text.casefold() in {"(entire category)", "entire category"}:
            sub_category_text = ""
        if not category_text:
            raise ValidationError("Category is required.")

        analysis = dict(boq.analysis_data or {})
        selections = dict(analysis.get("subcategory_make_selections") or {})
        storage_key = _subcategory_storage_key(category_text, sub_category_text)
        if storage_key not in selections:
            matched_key = next(
                (
                    key
                    for key, value in selections.items()
                    if isinstance(value, dict)
                    and _normalize_text(value.get("category"))
                    == _normalize_text(category_text)
                    and _normalize_text(value.get("sub_category"))
                    == _normalize_text(sub_category_text)
                    and str(value.get("source") or "").strip() == "manual"
                ),
                None,
            )
            if matched_key is None:
                raise ValidationError("That applied filter was not found.")
            storage_key = matched_key

        database_version_id = self._database_version_id(boq)
        rows = list(analysis.get("rows") or [])
        remaining = {
            key: value
            for key, value in selections.items()
            if key != storage_key and isinstance(value, dict)
        }
        boq_by_id = {
            str(row.get("row_id")): row
            for row in _ordered_boq_rows(boq.boq_data or {})
            if row.get("row_id")
        }
        cleared = self._restore_scope_to_lowest(
            rows,
            category=category_text,
            sub_category=sub_category_text,
            remaining=remaining,
            database_version_id=database_version_id,
            boq_by_id=boq_by_id,
            open_lowest=not self.has_make_list,
        )
        selections.pop(storage_key, None)
        stats = self._persist_filter_restore(
            boq,
            analysis,
            rows=rows,
            selections=selections,
            database_version_id=database_version_id,
        )
        logger.debug(
            "Sub-category filter removed boq=%s category=%s sub_category=%s cleared=%s",
            boq.pk,
            category_text,
            sub_category_text,
            cleared,
        )
        return {
            "category": category_text,
            "sub_category": sub_category_text,
            "cleared_count": cleared,
            "stats": stats,
        }

    def clear_all_subcategory_filters(self) -> dict[str, Any]:
        """Remove every manual cascade filter and restore those products to the
        same lowest-price state as the initial Make & Vendor page load.
        """
        boq = self._get_boq()
        self._ensure_editable(boq)

        analysis = dict(boq.analysis_data or {})
        selections = dict(analysis.get("subcategory_make_selections") or {})
        manuals = [
            value
            for value in selections.values()
            if isinstance(value, dict)
            and str(value.get("source") or "").strip() == "manual"
        ]
        if not manuals:
            raise ValidationError("No applied filters to clear.")

        database_version_id = self._database_version_id(boq)
        rows = list(analysis.get("rows") or [])
        remaining = {
            key: value
            for key, value in selections.items()
            if isinstance(value, dict)
            and str(value.get("source") or "").strip() != "manual"
        }
        boq_by_id = {
            str(row.get("row_id")): row
            for row in _ordered_boq_rows(boq.boq_data or {})
            if row.get("row_id")
        }
        open_lowest = not self.has_make_list
        cleared = 0
        for value in manuals:
            cleared += self._restore_scope_to_lowest(
                rows,
                category=str(value.get("category") or "").strip(),
                sub_category=str(value.get("sub_category") or "").strip(),
                remaining=remaining,
                database_version_id=database_version_id,
                boq_by_id=boq_by_id,
                open_lowest=open_lowest,
            )
        stats = self._persist_filter_restore(
            boq,
            analysis,
            rows=rows,
            selections=remaining,
            database_version_id=database_version_id,
        )
        logger.debug(
            "All sub-category filters cleared boq=%s filters=%s products=%s",
            boq.pk,
            len(manuals),
            cleared,
        )
        return {
            "filter_count": len(manuals),
            "cleared_count": cleared,
            "stats": stats,
        }


    def sync_analysis_product_ids(
        self,
        *,
        refresh_rates_if_changed: bool = True,
    ) -> dict[str, Any]:
        """
        Re-capture Product_IDs from Analysis without wiping unchanged Make & Vendor
        picks. Rates reload only when a product's Product_ID changed (or it still
        has no make/vendor selection). Manual Apply and cascade filters are kept.
        """
        boq = self._get_boq()
        self._ensure_editable(boq)

        database_version_id = self._database_version_id(boq)
        if not database_version_id:
            raise ValidationError("No active master database. Upload a database first.")

        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        boq_by_id = {
            str(row.get("row_id")): row
            for row in _ordered_boq_rows(boq.boq_data or {})
            if row.get("row_id")
        }

        captured_ids: list[str] = []
        changed_count = 0
        refreshed_count = 0
        updated_count = 0

        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                continue
            row_id = str(row.get("row_id") or "")
            qty = _field_from_map(analysis_fields(boq_by_id.get(row_id) or {}), _QTY_KEYS)
            row_changed = False
            for index, product in enumerate(products):
                previous_id = loaded_catalog_product_id(product)
                updated, product_id = self._capture_analysis_product_id(
                    product,
                    database_version_id=database_version_id,
                )
                id_changed = bool(
                    updated.pop("catalog_product_id_changed", False)
                    or (product_id and previous_id and product_id != previous_id)
                    or (product_id and not previous_id)
                )
                if product_id:
                    updated["catalog_product_id"] = product_id
                    captured_ids.append(product_id)

                selection = dict(updated.get("vendor_selection") or {})
                has_pick = bool(
                    selection.get("make")
                    or selection.get("vendor")
                    or selection.get("rate_detail")
                    or selection.get("status") in {"matched", "unmatched", "pending"}
                )
                # Only reload rates when Analysis Product_ID actually changed (or
                # there is no Make & Vendor pick yet). Preserve manual Apply /
                # cascade filter work when returning from Analysis.
                needs_rate_refresh = bool(
                    refresh_rates_if_changed
                    and product_id
                    and (id_changed or not has_pick)
                )
                if needs_rate_refresh:
                    category_text = str(updated.get("category") or "").strip()
                    sub_category_text = str(updated.get("sub_category") or "").strip()
                    approved_makes = self._approved_makes_for_subcategory(
                        category_text,
                        sub_category_text,
                    )
                    open_lowest = not self.has_make_list
                    match_payload = self._exact_match_and_rates(
                        updated,
                        make="",
                        vendor="",
                        quantity=(
                            updated.get("quantity")
                            if updated.get("quantity") not in (None, "")
                            else qty
                        ),
                        database_version_id=database_version_id,
                        prefer_lowest_price=True,
                        approved_makes=(
                            None if open_lowest else (approved_makes or None)
                        ),
                    )
                    match_payload["product_id"] = product_id
                    match_payload["catalog_product_id"] = product_id
                    applied_make = str(match_payload.get("make") or "").strip()
                    applied_vendor = str(match_payload.get("vendor") or "").strip()
                    rate_detail = match_payload.get("rate_detail") or {}
                    if not applied_make:
                        applied_make = str(rate_detail.get("make") or "").strip()
                    if not applied_vendor:
                        applied_vendor = str(rate_detail.get("vendor") or "").strip()
                    if applied_make:
                        match_payload["make"] = applied_make
                    if applied_vendor:
                        match_payload["vendor"] = applied_vendor
                    updated["vendor_selection"] = match_payload
                    updated["selected_make"] = applied_make or None
                    updated["selected_vendor"] = applied_vendor or None
                    if applied_make:
                        updated["make_hint"] = applied_make
                    updated["vendor_selection_source"] = "analysis_product_id_sync"
                    refreshed_count += 1
                elif product_id:
                    selection["product_id"] = product_id
                    selection["catalog_product_id"] = product_id
                    updated["vendor_selection"] = selection
                else:
                    updated = mark_product_not_available(
                        updated,
                        reason=REASON_NO_PRODUCT_ID,
                        quantity=(
                            updated.get("quantity")
                            if updated.get("quantity") not in (None, "")
                            else qty
                        ),
                    )
                    updated.pop("catalog_product_id", None)

                if id_changed:
                    changed_count += 1
                products[index] = updated
                updated_count += 1
                row_changed = True
            if row_changed:
                row["products"] = products

        analysis["rows"] = rows
        analysis["make_vendor_product_ids"] = sorted(set(captured_ids))
        analysis["database_version_id"] = database_version_id

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.info(
            "Synced Analysis Product_IDs boq=%s products=%s changed=%s refreshed=%s ids=%s",
            boq.pk,
            updated_count,
            changed_count,
            refreshed_count,
            len(set(captured_ids)),
        )
        return {
            "updated_count": updated_count,
            "changed_count": changed_count,
            "refreshed_count": refreshed_count,
            "product_id_count": len(set(captured_ids)),
            "product_ids": sorted(set(captured_ids)),
        }

    def apply_lowest_defaults_all(self, *, find_rates: bool = True) -> dict[str, Any]:
        """
        Analysis → Next: capture each product's Product_ID, then load rates.

        1. Snapshot every analysed product and resolve catalog ``Product_ID`` from
           the Analysis-selected Rate_Master row (``db_product_id`` / Select).
        2. Load Rate_Master_Output Make/Vendor rows for that Product_ID and pick
           the lowest ``Final_Material_Amount`` (make-list approved makes when set).
        """
        boq = self._get_boq()
        self._ensure_editable(boq)

        database_version_id = self._database_version_id(boq)
        if find_rates and not database_version_id:
            raise ValidationError("No active master database. Upload a database first.")

        analysis = dict(boq.analysis_data or {})
        missing_ids = count_missing_loaded_product_ids(analysis)
        # Missing Product Ids are allowed: those products are marked Not available
        # and skip Rate_Master / labour lookups (no block on Next).
        rows = list(analysis.get("rows") or [])
        boq_by_id = {
            str(row.get("row_id")): row
            for row in _ordered_boq_rows(boq.boq_data or {})
            if row.get("row_id")
        }

        # Phase 1 — capture updated products + Product_IDs from Analysis selection.
        captured_ids: list[str] = []
        not_available_count = 0
        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                continue
            captured: list[dict[str, Any]] = []
            for product in products:
                updated, product_id = self._capture_analysis_product_id(
                    product,
                    database_version_id=database_version_id,
                )
                if product_id:
                    updated["catalog_product_id"] = product_id
                    captured_ids.append(product_id)
                else:
                    not_available_count += 1
                captured.append(updated)
            row["products"] = captured

        # Prefer the pre-capture missing count when capture cleared stale ids.
        if missing_ids and not not_available_count:
            not_available_count = int(missing_ids)
        updated_count = 0
        matched_count = 0
        selections = dict(analysis.get("subcategory_make_selections") or {})
        pair_stats: dict[str, dict[str, Any]] = {}
        open_lowest = not self.has_make_list

        # Phase 2 — load Rate_Master rows by captured Product_ID for Make & Vendor.
        for row in rows:
            products = list(row.get("products") or [])
            if not products:
                continue
            row_id = str(row.get("row_id") or "")
            qty = _field_from_map(analysis_fields(boq_by_id.get(row_id) or {}), _QTY_KEYS)
            changed = False
            for index, product in enumerate(products):
                updated = dict(product)
                catalog_id = loaded_catalog_product_id(updated)
                category_text = str(updated.get("category") or "").strip()
                sub_category_text = str(updated.get("sub_category") or "").strip() or "—"
                if not catalog_id:
                    # No confirmed Analysis Product Id — Not available; no rate lookup.
                    updated = mark_product_not_available(
                        updated,
                        reason=REASON_NO_PRODUCT_ID,
                        quantity=(
                            updated.get("quantity")
                            if updated.get("quantity") not in (None, "")
                            else qty
                        ),
                    )
                    updated.pop("catalog_product_id", None)
                    match_payload = dict(updated.get("vendor_selection") or {})
                    source = NOT_AVAILABLE_SOURCE
                    approved_found = False
                else:
                    approved_makes = self._approved_makes_for_subcategory(
                        category_text,
                        sub_category_text if sub_category_text != "—" else "",
                    )
                    if self.has_make_list and not approved_makes:
                        if find_rates:
                            match_payload = self._exact_match_and_rates(
                                updated,
                                make="",
                                vendor="",
                                quantity=qty,
                                database_version_id=database_version_id,
                                prefer_lowest_price=True,
                                approved_makes=None,
                            )
                        else:
                            match_payload = {
                                "status": "unmatched",
                                "confidence": 0.0,
                                "notes": NO_APPROVED_MAKE_LABEL,
                                "make": "",
                                "vendor": "",
                                "rate_master_id": None,
                                "tech_key": "",
                                "summary": "",
                                "rate_detail": None,
                                "labour_detail": None,
                                "line_output": BOQLineOutputService.build(
                                    quantity=qty,
                                    rate_detail=None,
                                    labour_detail=None,
                                    is_pending=True,
                                ),
                                "prefer_lowest_price": True,
                                "matched_at": now_local_iso(),
                            }
                        if not match_payload.get("notes"):
                            match_payload["notes"] = NO_APPROVED_MAKE_LABEL
                        source = "not_found"
                        approved_found = False
                    else:
                        match_payload = self._exact_match_and_rates(
                            updated,
                            make="",
                            vendor="",
                            quantity=qty,
                            database_version_id=database_version_id,
                            prefer_lowest_price=True,
                            approved_makes=(
                                None if open_lowest else (approved_makes or None)
                            ),
                        )
                        source = "lowest_defaults"
                        approved_found = True if open_lowest else bool(approved_makes)
                    match_payload["product_id"] = catalog_id
                    match_payload["catalog_product_id"] = catalog_id

                applied_make = str(match_payload.get("make") or "").strip()
                applied_vendor = str(match_payload.get("vendor") or "").strip()
                rate_detail = match_payload.get("rate_detail") or {}
                if not applied_make:
                    applied_make = str(rate_detail.get("make") or "").strip()
                if not applied_vendor:
                    applied_vendor = str(rate_detail.get("vendor") or "").strip()
                if applied_make:
                    match_payload["make"] = applied_make
                if applied_vendor:
                    match_payload["vendor"] = applied_vendor
                updated["vendor_selection"] = match_payload
                updated["selected_make"] = applied_make or None
                updated["selected_vendor"] = applied_vendor or None
                if applied_make:
                    updated["make_hint"] = applied_make
                updated["approved_make_found"] = approved_found
                updated["vendor_selection_source"] = source
                if catalog_id:
                    updated["catalog_product_id"] = catalog_id
                if not category_text and rate_detail.get("category"):
                    updated["category"] = rate_detail.get("category")
                    category_text = str(rate_detail.get("category") or "").strip()
                if (
                    (not sub_category_text or sub_category_text == "—")
                    and rate_detail.get("sub_category")
                ):
                    updated["sub_category"] = rate_detail.get("sub_category")
                    sub_category_text = (
                        str(rate_detail.get("sub_category") or "").strip() or "—"
                    )
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
                        "vendor": applied_vendor,
                        "prefer_lowest_price": True,
                        "product_count": 0,
                    },
                )
                stats["product_count"] += 1
                if applied_make:
                    stats["make"] = applied_make
                if applied_vendor:
                    stats["vendor"] = applied_vendor
                if category_text:
                    stats["category"] = category_text
                if sub_category_text:
                    stats["sub_category"] = sub_category_text
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
        analysis["make_vendor_defaults_applied"] = True
        analysis["make_vendor_product_ids"] = sorted(set(captured_ids))
        if database_version_id:
            analysis["database_version_id"] = database_version_id

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            if boq.status not in {
                BOQStatus.LABOUR,
                BOQStatus.MATCHING,
                BOQStatus.PROCESSED,
                BOQStatus.READY_EXPORT,
                BOQStatus.EXPORTED,
            }:
                boq.status = BOQStatus.MAKE_VENDOR
            boq.save(update_fields=["analysis_data", "status"])

        logger.info(
            "Lowest make/vendor defaults applied boq=%s products=%s matched=%s "
            "product_ids=%s pairs=%s status=%s",
            boq.pk,
            updated_count,
            matched_count,
            len(set(captured_ids)),
            len(pair_stats),
            boq.status,
        )
        return {
            "updated_count": updated_count,
            "matched_count": matched_count,
            "pair_count": len(pair_stats),
            "product_id_count": len(set(captured_ids)),
            "not_available_count": int(not_available_count),
            "selections": list(pair_stats.values()),
            "make_vendor_defaults_applied": True,
            "status": boq.status,
        }


    def apply_category_make(
        self,
        *,
        category: str,
        make: str,
        vendor: str = "",
        find_rates: bool = True,
    ) -> dict[str, Any]:
        """Apply make/vendor to every analysed product in the category."""
        return self.apply_subcategory_make(
            category=category,
            sub_category="",
            make=make,
            vendor=vendor,
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


    def _build_selection_catalog(
        self,
        analysis: dict[str, Any],
        database_version_id: int,
    ) -> dict[str, Any]:
        """Cascade data for Make & Vendor: category → sub-category → make → vendor."""
        catalog = self._collect_extraction_catalog(analysis)
        stored = dict(analysis.get("subcategory_make_selections") or {})

        categories_out: list[dict[str, Any]] = []
        for category_row in catalog["categories"]:
            category = category_row["category"]
            cat_key = _normalize_text(category)
            category_make_options, category_concrete, category_selectable = (
                self._make_options_for_scope(
                    database_version_id=database_version_id,
                    category=category,
                    sub_category="",
                )
            )
            category_vendors_by_make: dict[str, list[str]] = {}
            for make_option in category_concrete:
                category_vendors_by_make[make_option] = self._vendors_for_subcategory_make(
                    database_version_id=database_version_id,
                    category=category,
                    sub_category="",
                    make=make_option,
                )
            category_preview = self._lowest_amount_maps(
                database_version_id=database_version_id,
                category=category,
                sub_category="",
                approved_makes=self._approved_makes_for_subcategory(category, "") or None,
            )

            sub_rows: list[dict[str, Any]] = []
            for sub_row in catalog["sub_categories_by_category"].get(cat_key, []):
                sub_category = sub_row["sub_category"]
                storage_key = _subcategory_storage_key(category, sub_category)
                selection = stored.get(storage_key) or {}
                make_options, concrete_makes, selectable = self._make_options_for_scope(
                    database_version_id=database_version_id,
                    category=category,
                    sub_category=sub_category,
                )
                selected_make = str(selection.get("make") or "").strip()
                if selectable and selection.get("prefer_lowest_price") and not selected_make:
                    selected_make = LOWEST_MAKE_LABEL
                elif selected_make and selected_make not in make_options and selectable:
                    make_options = [selected_make] + make_options

                vendors_by_make: dict[str, list[str]] = {}
                for make_option in concrete_makes:
                    vendors_by_make[make_option] = self._vendors_for_subcategory_make(
                        database_version_id=database_version_id,
                        category=category,
                        sub_category=sub_category,
                        make=make_option,
                    )

                selected_vendor = str(selection.get("vendor") or "").strip()
                vendor_options: list[str] = []
                if selected_make and not _is_lowest_make(selected_make):
                    vendor_options = list(vendors_by_make.get(selected_make) or [])
                if vendor_options:
                    vendor_options = [
                        item for item in vendor_options if not _is_lowest_make(item)
                    ]

                sub_rows.append(
                    {
                        "sub_category": sub_category,
                        "product_count": sub_row["product_count"],
                        "has_approved_makes": selectable,
                        "no_approved_make_label": NO_APPROVED_MAKE_LABEL,
                        "make_options": make_options,
                        "vendors_by_make": vendors_by_make,
                        "vendor_options": vendor_options,
                        "selected_make": selected_make if selectable else "",
                        "selected_vendor": selected_vendor if selectable else "",
                        "prefer_lowest_price": bool(selection.get("prefer_lowest_price")),
                        **self._lowest_amount_maps(
                            database_version_id=database_version_id,
                            category=category,
                            sub_category=sub_category,
                            approved_makes=self._approved_makes_for_subcategory(
                                category, sub_category
                            )
                            or None,
                        ),
                    }
                )
            categories_out.append(
                {
                    "category": category,
                    "product_count": category_row["product_count"],
                    "has_approved_makes": category_selectable,
                    "no_approved_make_label": NO_APPROVED_MAKE_LABEL,
                    "make_options": category_make_options,
                    "vendors_by_make": category_vendors_by_make,
                    "sub_categories": sub_rows,
                    **category_preview,
                }
            )

        applied_filters: list[dict[str, Any]] = []
        for key, value in stored.items():
            if not isinstance(value, dict):
                continue
            # Applied filters section shows only manual cascade applies — not auto defaults.
            if str(value.get("source") or "").strip() != "manual":
                continue
            category = str(value.get("category") or "").strip()
            sub_category = str(value.get("sub_category") or "").strip()
            if not category and _SUBCATEGORY_SEP in str(key):
                category, sub_category = str(key).split(_SUBCATEGORY_SEP, 1)
            applied_filters.append(
                {
                    "storage_key": str(key),
                    "category": category,
                    "sub_category": sub_category or "(entire category)",
                    "sub_category_value": sub_category,
                    "make": str(value.get("make") or "").strip() or "Lowest price",
                    "vendor": str(value.get("vendor") or "").strip()
                    or "Auto (lowest price)",
                    "amount": str(value.get("amount") or "").strip(),
                    "prefer_lowest_price": bool(value.get("prefer_lowest_price")),
                    "product_count": int(value.get("product_count") or 0),
                    "source": "manual",
                }
            )
        applied_filters.sort(
            key=lambda item: (
                str(item.get("category") or "").lower(),
                str(item.get("sub_category") or "").lower(),
            )
        )
        return {"categories": categories_out, "applied_filters": applied_filters}

