"""Rate_Master_Output lookup / option helpers for Make & Vendor."""
from __future__ import annotations

import logging
from typing import Any

from ai.embeddings.chroma_store import selection_amount
from apps.boq.services.boq_line_output_service import BOQLineOutputService
from apps.boq.services.boq_row_fields import (
    is_filled as _is_filled,
    normalize_text as _normalize_text,
)
from apps.boq.services.labour_detail_retrieval_service import LabourDetailRetrievalService
from apps.boq.services.make_list_constraint_service import (
    LOWEST_MAKE_LABEL,
    LOWEST_MAKE_STORED,
    LOWEST_MAKE_VALUE,
    MakeListConstraintService,
)
from apps.boq.services.make_vendor_common import (
    SAME_PRICE_TIE_LABEL,
    _align_option_label,
    _analysis_rate_master_pk,
    _build_same_price_choices,
    _catalog_product_id,
    _is_lowest_make,
    _product_summary,
)
from apps.boq.services.product_matching_service import structured_match_score
from apps.boq.services.rate_detail_retrieval_service import RateDetailRetrievalService
from apps.database_manager.models import Rate_Master_Output
from common.constants import MATCH_CONFIDENCE_THRESHOLD
from utils.timestamps import now_local_iso

logger = logging.getLogger("boq_ai")


class MakeVendorRatesMixin:
    """Rate index, dropdown options, and exact Rate_Master_Output matching."""

    # Provided by MakeVendorSelectionService.__init__ / has_make_list property.
    make_list_service: MakeListConstraintService
    has_make_list: bool
    _rate_index_version_id: int | None
    _rates_by_category: dict[str, list[dict[str, str]]]

    def _ensure_rate_index(self, database_version_id: int) -> None:
        """Load Make/Vendor rows once per service instance for dropdown builds."""
        if not database_version_id:
            self._rate_index_version_id = 0
            self._rates_by_category = {}
            return
        if self._rate_index_version_id == database_version_id:
            return
        rows = list(
            Rate_Master_Output.objects.filter(database_version_id=database_version_id)
            .exclude(Make__isnull=True)
            .exclude(Make="")
            .values("Category", "Sub_Category", "Make", "Vendor", "Final_Material_Amount")
        )
        by_category: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            category = str(row.get("Category") or "").strip()
            key = _normalize_text(category)
            if not key:
                continue
            amount = row.get("Final_Material_Amount")
            by_category.setdefault(key, []).append(
                {
                    "category": category,
                    "sub_category": str(row.get("Sub_Category") or "").strip(),
                    "make": str(row.get("Make") or "").strip(),
                    "vendor": str(row.get("Vendor") or "").strip(),
                    "amount": "" if amount is None else str(amount),
                }
            )
        self._rate_index_version_id = database_version_id
        self._rates_by_category = by_category


    def _rate_rows_for_scope(
        self,
        *,
        database_version_id: int,
        category: str,
        sub_category: str = "",
    ) -> list[dict[str, str]]:
        """Return cached Rate_Master rows for category, optionally narrowed by sub-category."""
        self._ensure_rate_index(database_version_id)
        category_key = _normalize_text(category)
        if not category_key:
            return []
        rows = list(self._rates_by_category.get(category_key) or [])
        sub_text = str(sub_category or "").strip()
        if not sub_text or sub_text == "—":
            return rows
        sub_key = _normalize_text(sub_text)
        narrowed = [
            row
            for row in rows
            if _normalize_text(row.get("sub_category") or "") == sub_key
        ]
        # Keep sub-category scope strict — do not fall back to every make in the
        # parent category (that flooded the Approved make cascade dropdown).
        return narrowed


    def _approved_makes_for_subcategory(self, category: str, sub_category: str) -> list[str]:
        """Approved makes for cascade scope — sub-specific when a sub is selected."""
        sub_text = str(sub_category or "").strip()
        if sub_text == "—":
            sub_text = ""
        # Cascade with an explicit sub: prefer makes mapped to that sub only.
        if sub_text:
            specific = self.make_list_service.approved_makes_for_category(
                category,
                sub_text,
                allow_category_wide=False,
            )
            if specific:
                return list(specific)
            # No sub-specific make-list row: keep category-wide approved makes, but
            # the dropdown will intersect them with Rate_Master makes for this sub.
            approved = self.make_list_service.approved_makes_for_category(
                category,
                sub_text,
                allow_category_wide=True,
            )
            return list(approved or [])
        approved = self.make_list_service.approved_makes_for_category(category, "")
        return list(approved or [])


    def _rate_master_makes_for_subcategory(
        self,
        *,
        database_version_id: int,
        category: str,
        sub_category: str,
    ) -> list[str]:
        """Distinct Rate_Master_Output makes for category / optional sub-category."""
        if not database_version_id or not (category or "").strip():
            return []
        makes: list[str] = []
        seen: set[str] = set()
        for rate in self._rate_rows_for_scope(
            database_version_id=database_version_id,
            category=category,
            sub_category=sub_category,
        ):
            text = (rate.get("make") or "").strip()
            key = _normalize_text(text)
            if text and key not in seen:
                seen.add(key)
                makes.append(text)
        return sorted(makes, key=lambda item: item.lower())

    def _all_database_makes(self, database_version_id: int) -> list[str]:
        """All distinct Makes in Rate_Master_Output for a database version."""
        if not database_version_id:
            return []
        if not hasattr(self, "_cached_db_makes"):
            self._cached_db_makes = {}
        if database_version_id not in self._cached_db_makes:
            makes = list(
                Rate_Master_Output.objects.filter(database_version_id=database_version_id)
                .values_list("Make", flat=True)
                .distinct()
            )
            seen: set[str] = set()
            out: list[str] = []
            for item in makes:
                text = str(item or "").strip()
                key = _normalize_text(text)
                if text and key not in seen:
                    seen.add(key)
                    out.append(text)
            self._cached_db_makes[database_version_id] = sorted(out, key=lambda s: s.lower())
        return self._cached_db_makes[database_version_id]

    def _all_database_vendors(self, database_version_id: int) -> list[str]:
        """All distinct Vendors in Rate_Master_Output for a database version."""
        if not database_version_id:
            return []
        if not hasattr(self, "_cached_db_vendors"):
            self._cached_db_vendors = {}
        if database_version_id not in self._cached_db_vendors:
            vendors = list(
                Rate_Master_Output.objects.filter(database_version_id=database_version_id)
                .values_list("Vendor", flat=True)
                .distinct()
            )
            seen: set[str] = set()
            out: list[str] = []
            for item in vendors:
                text = str(item or "").strip()
                key = _normalize_text(text)
                if text and key not in seen:
                    seen.add(key)
                    out.append(text)
            self._cached_db_vendors[database_version_id] = sorted(out, key=lambda s: s.lower())
        return self._cached_db_vendors[database_version_id]


    def _format_preview_amount(self, value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ""
        if number < 0:
            return ""
        return f"{number:.2f}"

    def _lowest_amount_maps(
        self,
        *,
        database_version_id: int,
        category: str,
        sub_category: str,
        approved_makes: list[str] | None,
    ) -> dict[str, Any]:
        """Lowest Final_Material_Amount for cascade preview (scope / make / vendor)."""
        overall: float | None = None
        by_make: dict[str, float] = {}
        by_make_vendor: dict[str, dict[str, float]] = {}
        for rate in self._rate_rows_for_scope(
            database_version_id=database_version_id,
            category=category,
            sub_category=sub_category,
        ):
            make = (rate.get("make") or "").strip()
            vendor = (rate.get("vendor") or "").strip()
            if not make:
                continue
            if approved_makes and not MakeListConstraintService.make_is_allowed(
                make, approved_makes
            ):
                continue
            try:
                amount = float(rate.get("amount") or "")
            except (TypeError, ValueError):
                continue
            if overall is None or amount < overall:
                overall = amount
            current_make = by_make.get(make)
            if current_make is None or amount < current_make:
                by_make[make] = amount
            if vendor:
                vendor_map = by_make_vendor.setdefault(make, {})
                current_vendor = vendor_map.get(vendor)
                if current_vendor is None or amount < current_vendor:
                    vendor_map[vendor] = amount
        return {
            "lowest_amount": self._format_preview_amount(overall) if overall is not None else "",
            "lowest_by_make": {
                make: self._format_preview_amount(amount)
                for make, amount in by_make.items()
            },
            "lowest_by_make_vendor": {
                make: {
                    vendor: self._format_preview_amount(amount)
                    for vendor, amount in vendors.items()
                }
                for make, vendors in by_make_vendor.items()
            },
        }


    def _make_options_for_scope(
        self,
        *,
        database_version_id: int,
        category: str,
        sub_category: str,
    ) -> tuple[list[str], list[str], bool]:
        """
        Return ``(make_options, concrete_makes, selectable)``.

        With make list: approved makes only (or empty / not selectable).
        Without make list: Lowest price + Rate_Master_Output makes.
        When a sub-category is selected, only makes that exist on Rate_Master for
        that sub (and are approved, if a make list is present) are listed.
        """
        sub_text = str(sub_category or "").strip()
        rate_makes = self._rate_master_makes_for_subcategory(
            database_version_id=database_version_id,
            category=category,
            sub_category=sub_category,
        )
        approved = self._approved_makes_for_subcategory(category, sub_category)

        if self.has_make_list:
            if sub_text and sub_text != "—":
                # Explicit sub: intersect approved makes with Rate_Master for that sub
                # so SIEMENS/L&T from unrelated make-list lines do not appear.
                if approved and rate_makes:
                    scoped = [
                        make
                        for make in approved
                        if MakeListConstraintService.make_is_allowed(make, rate_makes)
                    ]
                    if scoped:
                        return [LOWEST_MAKE_LABEL] + list(scoped), list(scoped), True
                if approved and not rate_makes:
                    # Make-list has sub/category makes but no Rate_Master rows yet.
                    return [LOWEST_MAKE_LABEL] + list(approved), list(approved), True
                if rate_makes:
                    return list(rate_makes), list(rate_makes), True
                return [], [], False
            if not approved:
                if rate_makes:
                    return list(rate_makes), list(rate_makes), bool(rate_makes)
                return [], [], False
            return [LOWEST_MAKE_LABEL] + list(approved), list(approved), True

        if rate_makes:
            return [LOWEST_MAKE_LABEL] + list(rate_makes), list(rate_makes), True
        return [], [], False


    def _vendors_for_subcategory_make(
        self,
        *,
        database_version_id: int,
        category: str,
        sub_category: str,
        make: str,
    ) -> list[str]:
        if not database_version_id or not make or _is_lowest_make(make):
            return []

        def _collect(rows: list[dict[str, str]]) -> list[str]:
            vendors: list[str] = []
            seen: set[str] = set()
            for rate in rows:
                if not MakeListConstraintService.make_is_allowed(
                    rate.get("make"), [make]
                ):
                    continue
                text = (rate.get("vendor") or "").strip()
                key = _normalize_text(text)
                if text and key not in seen:
                    seen.add(key)
                    vendors.append(text)
            return sorted(vendors, key=lambda item: item.lower())

        scoped = self._rate_rows_for_scope(
            database_version_id=database_version_id,
            category=category,
            sub_category=sub_category,
        )
        vendors = _collect(scoped)
        # Sub-category may be too narrow for vendor variety — fall back to category.
        if (
            len(vendors) < 2
            and (sub_category or "").strip()
            and sub_category != "—"
        ):
            category_vendors = _collect(
                self._rate_rows_for_scope(
                    database_version_id=database_version_id,
                    category=category,
                    sub_category="",
                )
            )
            if len(category_vendors) > len(vendors):
                return category_vendors
        return vendors


    def _capture_analysis_product_id(
        self,
        product: dict[str, Any],
        *,
        database_version_id: int,
    ) -> tuple[dict[str, Any], str]:
        """Persist the Analysis-selected catalog Product_ID on the product.

        Only products with a confirmed Analysis Product Id (orange/green match or
        expert Select) are captured. Weak/red matches keep blank Product Id and
        become Not available on Make & Vendor — same rules as the Analysis tab.
        """
        from apps.boq.services.make_vendor_common import loaded_catalog_product_id

        updated = dict(product)
        loaded_id = loaded_catalog_product_id(updated)
        if not loaded_id:
            updated.pop("catalog_product_id", None)
            return updated, ""

        previous = str(updated.get("catalog_product_id") or "").strip()
        if not previous:
            selection = updated.get("vendor_selection") or {}
            previous = str(
                selection.get("catalog_product_id") or selection.get("product_id") or ""
            ).strip()

        rate_pk = _analysis_rate_master_pk(updated)
        if rate_pk is not None and database_version_id:
            rate = Rate_Master_Output.objects.filter(
                pk=rate_pk,
                database_version_id=database_version_id,
            ).first()
            product_id = str(getattr(rate, "Product_ID", "") or "").strip() if rate else ""
            if product_id:
                updated["catalog_product_id"] = product_id
                updated["db_product_id"] = rate_pk
                if rate is not None and not str(updated.get("category") or "").strip():
                    updated["category"] = rate.Category
                if rate is not None and not str(updated.get("sub_category") or "").strip():
                    updated["sub_category"] = rate.Sub_Category
                if previous and previous != product_id:
                    updated["catalog_product_id_changed"] = True
                else:
                    updated.pop("catalog_product_id_changed", None)
                return updated, product_id

        updated["catalog_product_id"] = loaded_id
        updated.pop("catalog_product_id_changed", None)
        return updated, loaded_id

    def _ensure_catalog_product_id(
        self,
        product: dict[str, Any],
        *,
        database_version_id: int,
    ) -> dict[str, Any]:
        """Attach Product_Helper Product_ID when Analysis left it blank."""
        if _catalog_product_id(product):
            return product
        from apps.boq.services.product_helper_matching_service import (
            ProductHelperMatchingService,
        )

        updated = dict(product)
        try:
            match = ProductHelperMatchingService(database_version_id).match_product(
                updated
            )
        except Exception:
            logger.exception("Product_Helper lookup failed during Make & Vendor Next")
            return updated
        best = match.get("best") or {}
        product_id = str(best.get("product_id") or "").strip()
        confidence = float(match.get("confidence") or 0.0)
        if not product_id or confidence < MATCH_CONFIDENCE_THRESHOLD:
            return updated
        updated["catalog_product_id"] = product_id
        updated["product_helper_id"] = best.get("product_helper_id")
        updated["catalog_match_confidence"] = confidence
        return updated


    def _options_for_product(
        self,
        product: dict[str, Any],
        *,
        database_version_id: int,
        boq_description: str,
    ) -> tuple[list[str], list[str], dict[str, list[str]], dict[str, list[str]]]:
        catalog_product_id = _catalog_product_id(product)
        if catalog_product_id:
            return self._options_for_catalog_product_id(
                catalog_product_id,
                database_version_id=database_version_id,
                product=product,
            )

        category = str(product.get("category") or "")
        sub_category = str(product.get("sub_category") or "")
        preferred_makes, concrete_makes, _selectable = self._make_options_for_scope(
            database_version_id=database_version_id,
            category=category,
            sub_category=sub_category,
        )

        selected_make = str(
            (product.get("vendor_selection") or {}).get("make")
            or product.get("selected_make")
            or ""
        ).strip()
        selected_vendor = str(
            (product.get("vendor_selection") or {}).get("vendor")
            or product.get("selected_vendor")
            or ""
        ).strip()
        selected_make = _align_option_label(selected_make, preferred_makes + concrete_makes)

        makes = list(preferred_makes)
        vendors_by_make: dict[str, list[str]] = {}
        makes_by_vendor: dict[str, list[str]] = {}
        for make_option in concrete_makes:
            vendors = self._vendors_for_subcategory_make(
                database_version_id=database_version_id,
                category=category,
                sub_category=sub_category,
                make=make_option,
            )
            vendors_by_make[make_option] = vendors
            for vendor in vendors:
                makes_by_vendor.setdefault(vendor, [])
                if make_option not in makes_by_vendor[vendor]:
                    makes_by_vendor[vendor].append(make_option)
        if selected_make and selected_make not in makes and selected_make not in {
            LOWEST_MAKE_VALUE,
            LOWEST_MAKE_STORED,
            "",
        }:
            makes = [selected_make, *makes]
            vendors_by_make[selected_make] = self._vendors_for_subcategory_make(
                database_version_id=database_version_id,
                category=category,
                sub_category=sub_category,
                make=selected_make,
            )
            for vendor in vendors_by_make[selected_make]:
                makes_by_vendor.setdefault(vendor, [])
                if selected_make not in makes_by_vendor[vendor]:
                    makes_by_vendor[vendor].append(selected_make)

        vendor_options: list[str] = []
        if selected_make and selected_make not in {LOWEST_MAKE_VALUE, LOWEST_MAKE_STORED, ""}:
            vendor_options = [
                item
                for item in (vendors_by_make.get(selected_make) or [])
                if item
            ]
        else:
            # All vendors for this Product scope — used when Make is empty / Lowest.
            seen: set[str] = set()
            for values in vendors_by_make.values():
                for vendor in values:
                    key = _normalize_text(vendor)
                    if vendor and key not in seen:
                        seen.add(key)
                        vendor_options.append(vendor)
        if not self.has_make_list:
            all_db_vendors = self._all_database_vendors(database_version_id)
            seen_v = {_normalize_text(v) for v in vendor_options}
            for v in all_db_vendors:
                key = _normalize_text(v)
                if key not in seen_v:
                    seen_v.add(key)
                    vendor_options.append(v)

        selected_vendor = _align_option_label(selected_vendor, vendor_options)
        if selected_vendor and selected_vendor not in vendor_options:
            vendor_options = [selected_vendor, *vendor_options]

        return makes, vendor_options, vendors_by_make, makes_by_vendor


    def _options_for_catalog_product_id(
        self,
        product_id: str,
        *,
        database_version_id: int,
        product: dict[str, Any],
    ) -> tuple[list[str], list[str], dict[str, list[str]], dict[str, list[str]]]:
        """Make/Vendor pair maps from Rate_Master_Output rows for one Product_ID."""
        rates = list(
            Rate_Master_Output.objects.filter(
                database_version_id=database_version_id,
                Product_ID=product_id,
            ).order_by("Make", "Vendor", "pk")
        )
        if self.has_make_list:
            category = str(product.get("category") or "")
            sub_category = str(product.get("sub_category") or "")
            approved = self._approved_makes_for_subcategory(category, sub_category)
            if approved:
                filtered = MakeListConstraintService.filter_rate_ids_by_make(rates, approved)
                if filtered:
                    rates = filtered
                # else keep all Product_ID rates so Make dropdown still fills

        makes: list[str] = []
        vendor_options: list[str] = []
        vendors_by_make: dict[str, list[str]] = {}
        makes_by_vendor: dict[str, list[str]] = {}
        seen_makes: set[str] = set()
        seen_vendors: set[str] = set()
        for rate in rates:
            make = str(rate.Make or "").strip()
            vendor = str(rate.Vendor or "").strip()
            if not make:
                continue
            make_key = _normalize_text(make)
            if make_key not in seen_makes:
                seen_makes.add(make_key)
                makes.append(make)
            vendors_by_make.setdefault(make, [])
            if vendor and vendor not in vendors_by_make[make]:
                vendors_by_make[make].append(vendor)
            if vendor:
                vendor_key = _normalize_text(vendor)
                if vendor_key not in seen_vendors:
                    seen_vendors.add(vendor_key)
                    vendor_options.append(vendor)
                makes_by_vendor.setdefault(vendor, [])
                if make not in makes_by_vendor[vendor]:
                    makes_by_vendor[vendor].append(make)

        if not self.has_make_list:
            all_db_makes = self._all_database_makes(database_version_id)
            for m in all_db_makes:
                m_key = _normalize_text(m)
                if m_key not in seen_makes:
                    seen_makes.add(m_key)
                    makes.append(m)
            all_db_vendors = self._all_database_vendors(database_version_id)
            for v in all_db_vendors:
                v_key = _normalize_text(v)
                if v_key not in seen_vendors:
                    seen_vendors.add(v_key)
                    vendor_options.append(v)

        selected_make = str(
            (product.get("vendor_selection") or {}).get("make")
            or product.get("selected_make")
            or ""
        ).strip()
        selected_vendor = str(
            (product.get("vendor_selection") or {}).get("vendor")
            or product.get("selected_vendor")
            or ""
        ).strip()
        # Align make-list spellings onto Rate_Master option labels before maps.
        selected_make = _align_option_label(selected_make, makes)
        selected_vendor = _align_option_label(selected_vendor, vendor_options)
        if selected_make and selected_make not in makes and selected_make not in {
            LOWEST_MAKE_VALUE,
            LOWEST_MAKE_STORED,
            "",
        }:
            makes = [selected_make, *makes]
            vendors_by_make.setdefault(selected_make, [])
        if selected_vendor and selected_vendor not in vendor_options:
            vendor_options = [selected_vendor, *vendor_options]
            makes_by_vendor.setdefault(selected_vendor, [])
        if (
            selected_make
            and selected_vendor
            and selected_make not in {LOWEST_MAKE_VALUE, LOWEST_MAKE_STORED, ""}
        ):
            vendors_by_make.setdefault(selected_make, [])
            if selected_vendor not in vendors_by_make[selected_make]:
                vendors_by_make[selected_make].append(selected_vendor)
            makes_by_vendor.setdefault(selected_vendor, [])
            if selected_make not in makes_by_vendor[selected_vendor]:
                makes_by_vendor[selected_vendor].append(selected_make)
        return makes, vendor_options, vendors_by_make, makes_by_vendor


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
    ) -> dict[str, Any]:
        extracted = dict(product)
        if make:
            extracted["make_hint"] = make

        queryset = Rate_Master_Output.objects.filter(
            database_version_id=database_version_id
        )
        # Prefer Product_Helper Product_ID when known — rates are Make/Vendor variants.
        catalog_product_id = _catalog_product_id(extracted)
        if catalog_product_id:
            queryset = queryset.filter(Product_ID=catalog_product_id)
        # Do not filter Make with exact SQL — approved-list names can differ slightly
        # from Rate_Master_Output.Make; optimal matching runs in Python below.
        if vendor:
            queryset = queryset.filter(Vendor__iexact=vendor)

        category = extracted.get("category")
        sub_category = extracted.get("sub_category")
        if not catalog_product_id:
            if _is_filled(category):
                queryset = queryset.filter(Category__iexact=str(category).strip())
            if _is_filled(sub_category):
                narrowed = queryset.filter(Sub_Category__iexact=str(sub_category).strip())
                if narrowed.exists():
                    queryset = narrowed

        rate_rows = list(queryset[:500])
        make_filter = [make] if make else None
        if approved_makes:
            rate_rows = MakeListConstraintService.filter_rate_ids_by_make(
                rate_rows, approved_makes
            )
        elif make_filter:
            rate_rows = MakeListConstraintService.filter_rate_ids_by_make(
                rate_rows, make_filter
            )
        elif prefer_lowest_price and self.has_make_list:
            # Constrain to approved makes when the make list has them for this scope.
            # When Product_ID is known but no approved make exists, keep all Rate_Master
            # rows for that Product_ID so Next / Find in DB can still load combinations.
            approved = self._approved_makes_for_subcategory(
                str(category or ""),
                str(sub_category or ""),
            )
            if approved:
                filtered = MakeListConstraintService.filter_rate_ids_by_make(
                    rate_rows, approved
                )
                # Approved labels that do not optimally match Rate_Master.Make used to
                # wipe every row → empty Make on Next. Keep Product_ID rates instead.
                if filtered:
                    rate_rows = filtered
                elif not catalog_product_id:
                    rate_rows = []
            elif not catalog_product_id:
                rate_rows = []
        # No make list + prefer_lowest_price: keep Product_ID / category rows as-is.
        if make and approved_makes:
            rate_rows = [
                row
                for row in rate_rows
                if MakeListConstraintService.make_is_allowed(row.Make, [make])
            ]
        elif make and not approved_makes:
            rate_rows = MakeListConstraintService.filter_rate_ids_by_make(
                rate_rows, [make]
            )
        scored: list[tuple[float, Rate_Master_Output, dict[str, Any], float]] = []
        for rate in rate_rows:
            structured, breakdown = structured_match_score(extracted, rate)
            if vendor and _normalize_text(rate.Vendor) == _normalize_text(vendor):
                structured = min(100.0, structured + 5.0)
            # Always compare / display Final_Material_Amount (never Net_Material_Rate).
            amount = float(selection_amount(rate))
            scored.append((structured, rate, breakdown, amount))

        if prefer_lowest_price and scored:
            # Among Rate_Master rows for this Product_ID (or scoped taxonomy),
            # pick lowest Final_Material_Amount; break ties with structured score.
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
                "vendor": vendor,
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
                "notes": "No Rate_Master_Output row found with the selected make/vendor.",
                "same_price_tie": False,
                "same_price_choices": [],
                "matched_at": now_local_iso(),
            }

        same_price_choices: list[dict[str, Any]] = []
        if prefer_lowest_price and not vendor:
            same_price_choices = _build_same_price_choices(scored)

        confidence, rate, breakdown, _amount = scored[0]
        rate_service = RateDetailRetrievalService(database_version_id)
        labour_service = LabourDetailRetrievalService(database_version_id)
        rate_detail = rate_service.get_by_id(rate.pk)
        labour_detail = labour_service.get_by_product_id(rate.Product_ID)
        status = "matched" if confidence >= MATCH_CONFIDENCE_THRESHOLD else "pending"
        qty_value = (
            extracted.get("quantity")
            if extracted.get("quantity") not in (None, "")
            else quantity
        )
        line_output = BOQLineOutputService.build(
            quantity=qty_value,
            rate_detail=rate_detail,
            labour_detail=labour_detail,
            is_pending=status != "matched",
            rate_only=bool(extracted.get("rate_only")),
        )
        resolved_make = MakeListConstraintService.resolve_canonical_make(
            make or (rate.Make or ""),
            approved_makes,
        )
        # Prefer Rate_Master Make/Vendor for UI selection so dropdown options match.
        # Make-list canonical labels (NEWAGE vs NEW AGE) are for filtering only.
        display_make = (rate.Make or "").strip() or resolved_make or make
        display_vendor = (rate.Vendor or "").strip() or vendor
        notes = ""
        if same_price_choices:
            notes = SAME_PRICE_TIE_LABEL
        elif status != "matched":
            notes = "Closest Rate_Master_Output row found — review make/vendor or product fields."
        return {
            "make": display_make,
            "vendor": display_vendor,
            "status": status,
            "confidence": round(confidence, 2),
            "rate_master_id": rate.pk,
            "product_id": rate.Product_ID,
            "rate_id": rate.Rate_ID,
            "tech_key": rate.display_key(),
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
            "notes": notes,
            "prefer_lowest_price": prefer_lowest_price,
            "same_price_tie": bool(same_price_choices),
            "same_price_choices": same_price_choices,
            "matched_at": now_local_iso(),
        }

