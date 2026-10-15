"""Make & Vendor tab display shaping."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from apps.boq.services.boq_extraction_service import (
    normalize_product_fields,
    quantity_display_fields,
    rehydrate_products_quantity_from_group,
)
from apps.boq.services.boq_row_fields import (
    DESCRIPTION_KEYS as _DESCRIPTION_KEYS,
    QTY_KEYS as _QTY_KEYS,
    UNIT_KEYS as _UNIT_KEYS,
    field_from_map as _field_from_map,
    ordered_boq_rows as _ordered_boq_rows,
    resolve_activity_only,
)
from apps.boq.services.make_list_constraint_service import (
    NO_APPROVED_MAKE_LABEL,
    MakeListConstraintService,
    makes_optimally_match,
)
from apps.boq.services.make_vendor_common import (
    NOT_AVAILABLE_LABEL,
    NOT_AVAILABLE_SOURCE,
    NOT_AVAILABLE_STATUS,
    NOT_IN_DB_LABEL,
    NOT_LISTED_LABEL,
    SAME_PRICE_TIE_LABEL,
    _align_option_label,
    _catalog_product_id,
    _flag_same_material_rate_vendor_review,
    _is_lowest_make,
    _product_summary,
    _taxonomy_label,
    is_product_not_available,
    loaded_catalog_product_id,
)
from apps.boq.services.serial_normalizer import analysis_fields

def _make_in_options(make: str, options: list[str] | None) -> bool:
    if not make or not options:
        return False
    for opt in options:
        if makes_optimally_match(make, opt):
            return True
    return False


class MakeVendorDisplayMixin:
    """Build Make & Vendor tab lines and product cards."""

    if TYPE_CHECKING:
        has_make_list: bool

        def _get_boq(self) -> BOQ: ...
        def _database_version_id(self, boq: BOQ) -> int: ...
        def _ensure_rate_index(self, database_version_id: int) -> None: ...
        def _build_selection_catalog(
            self, analysis: dict[str, Any], database_version_id: int
        ) -> dict[str, Any]: ...
        def _options_for_product(
            self,
            product: dict[str, Any],
            *,
            database_version_id: int,
            boq_description: str,
        ) -> tuple[list[str], list[str], list[str], dict[str, list[str]], dict[str, list[str]]]: ...
        def _vendors_for_subcategory_make(
            self,
            *,
            database_version_id: int,
            category: str,
            sub_category: str,
            make: str,
        ) -> list[str]: ...
        def _approved_makes_for_subcategory(
            self, category: str, sub_category: str, *, allow_category_wide: bool = False
        ) -> list[str]: ...

    def build_display(self) -> dict[str, Any]:
        from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows

        boq = self._get_boq()
        analysis = boq.analysis_data or {}
        if not analysis.get("rows"):
            return {"has_products": False, "lines": [], "categories": [], "stats": {}}

        database_version_id = self._database_version_id(boq)
        # One Rate_Master_Output read for all make/vendor dropdowns on this page.
        self._ensure_rate_index(database_version_id)
        analysis_by_row = {
            str(row.get("row_id")): row
            for row in analysis.get("rows") or []
            if row.get("row_id")
        }

        # Build lineage lookup from BOQ grouping so Make & Vendor shows the same
        # section format as Analysis (grouped lines, description, slots).
        group_by_row: dict[str, dict[str, Any]] = {}
        for group in grouped_anchor_rows(boq.boq_data or {}):
            group_by_row[str(group.get("row_id") or "")] = group

        lines: list[dict[str, Any]] = []
        selected_count = 0
        matched_count = 0
        product_count = 0
        default_count = 0
        filtered_count = 0
        not_found_count = 0
        no_match_count = 0
        not_available_count = 0
        same_price_tie_count = 0

        for boq_row in _ordered_boq_rows(boq.boq_data or {}):
            row_id = str(boq_row.get("row_id") or "")
            analysis_row = analysis_by_row.get(row_id, {})
            if analysis_row.get("skip_reason") == "lineage_child_row":
                continue
            products = list(analysis_row.get("products") or [])
            group = group_by_row.get(row_id, {})

            fields = analysis_fields(boq_row)
            qty = group.get("qty")
            unit = group.get("unit")
            qty_status = str(group.get("qty_status") or "empty")
            qty_rows = list(group.get("qty_rows") or [])
            if qty in (None, "") and qty_rows:
                qty = qty_rows[0].get("qty")
                unit = unit or qty_rows[0].get("unit")
                qty_status = str(qty_rows[0].get("qty_status") or qty_status)
            if qty in (None, "") and not qty_rows:
                qty = _field_from_map(fields, _QTY_KEYS)
                unit = unit or _field_from_map(fields, _UNIT_KEYS)
            description = _field_from_map(fields, _DESCRIPTION_KEYS) or ""

            is_act_only = resolve_activity_only(
                analysis_row,
                products=products,
                units=[
                    unit,
                    group.get("unit"),
                    *[row.get("unit") for row in qty_rows],
                ],
            )

            if not products and not is_act_only:
                continue

            if is_act_only:
                products = []

            products = rehydrate_products_quantity_from_group(products, group)

            shaped_products = []
            for index, product in enumerate(products):
                product_qty = (
                    product.get("quantity")
                    if product.get("quantity") not in (None, "")
                    else qty
                )
                product_unit = (
                    product.get("quantity_unit")
                    if product.get("quantity_unit") not in (None, "")
                    else unit
                )
                shaped = self._shape_product(
                    product,
                    row_id=row_id,
                    qty=product_qty,
                    unit=product_unit,
                    database_version_id=database_version_id,
                    boq_description=description,
                )
                product_index = int(shaped.get("product_index") or index)
                shaped["product_index"] = product_index
                shaped["display_number"] = product_index + 1
                product_count += 1
                if shaped.get("selected_make") or shaped.get("selected_vendor"):
                    selected_count += 1
                match_status = str(shaped.get("match_status") or "not_searched")
                if match_status == "matched":
                    matched_count += 1
                make_status = shaped.get("make_status") or "default"
                if shaped.get("is_not_available"):
                    not_available_count += 1
                elif make_status == "not_found":
                    not_found_count += 1
                elif match_status == "unmatched":
                    no_match_count += 1
                elif make_status == "filtered":
                    filtered_count += 1
                else:
                    default_count += 1
                if shaped.get("same_price_tie"):
                    same_price_tie_count += 1
                shaped_products.append(shaped)

            # Determine line-level status for border coloring.
            if any(p.get("is_not_available") for p in shaped_products):
                line_status = "not_available"
            elif any(p.get("highlight_no_make") for p in shaped_products):
                line_status = "not_found"
            elif any(p.get("same_price_tie") for p in shaped_products):
                line_status = "same_price"
            elif any(str(p.get("match_status") or "") == "unmatched" for p in shaped_products):
                line_status = "no_match"
            elif all(str(p.get("match_status") or "") == "matched" for p in shaped_products) and shaped_products:
                line_status = "matched"
            else:
                line_status = "default"

            # Line badge: Auto (lowest-price default) vs filtered (expert make pick).
            if shaped_products and any(
                str(product.get("make_status") or "default") == "filtered"
                for product in shaped_products
            ):
                selection_mode = "filtered"
            elif shaped_products:
                selection_mode = "Auto"
            else:
                selection_mode = ""

            show_qty_unit = qty_status in {"numeric", "zero", "rate_only", "multi"} or qty not in (
                None,
                "",
            )
            if show_qty_unit and qty in (None, ""):
                qty_display = "—"
            elif show_qty_unit:
                qty_display = str(qty)
            else:
                qty_display = ""
            unit_display = str(unit).strip() if unit not in (None, "") else "—"

            if is_act_only:
                shaped_products = []
                selection_mode = ""
                line_status = "default"

            lines.append(
                {
                    "row_id": row_id,
                    "serial": boq_row.get("serial") or "",
                    "depth": boq_row.get("depth") or 0,
                    "description": group.get("description") or description,
                    "full_description": group.get("full_description") or description,
                    "lineage_parts": group.get("lineage_parts") or [],
                    "lineage_count": int(group.get("lineage_count") or 1),
                    "slot_count": int(group.get("slot_count") or 0),
                    "qty": qty,
                    "unit": unit,
                    "qty_display": qty_display,
                    "unit_display": unit_display,
                    "show_qty_unit": show_qty_unit,
                    "products": shaped_products,
                    "product_count": len(shaped_products),
                    "is_activity_only": is_act_only,
                    "line_status": line_status,
                    "selection_mode": selection_mode,
                }
            )

        vendor_review_count = 0

        return {
            "has_products": len(lines) > 0 or product_count > 0 or bool(analysis.get("rows")),
            "database_version_id": database_version_id,
            "stats": {
                "product_count": product_count,
                "selected_count": selected_count,
                "matched_count": matched_count,
                "default_count": default_count,
                "filtered_count": filtered_count,
                "not_found_count": not_found_count,
                "no_match_count": no_match_count,
                "not_available_count": not_available_count,
                "vendor_review_count": vendor_review_count,
                "same_price_tie_count": same_price_tie_count,
            },
            "selection_catalog": self._build_selection_catalog(analysis, database_version_id),
            "lines": lines,
        }


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
        product = normalize_product_fields(product)
        selection = dict(product.get("vendor_selection") or {})
        catalog_id = _catalog_product_id(product)
        (
            approved_make_options,
            available_make_options,
            vendor_options,
            vendors_by_make,
            makes_by_vendor,
        ) = self._options_for_product(
            product,
            database_version_id=database_version_id,
            boq_description=boq_description,
        )
        rate_detail = selection.get("rate_detail")
        labour_detail = selection.get("labour_detail")
        line_output = selection.get("line_output")

        selected_make = str(product.get("selected_make") or selection.get("make") or "").strip()
        if not selected_make or _is_lowest_make(selected_make):
            candidate = str(
                (rate_detail or {}).get("make")
                or (rate_detail or {}).get("Make")
                or selection.get("make")
                or product.get("make_hint")
                or ""
            ).strip()
            if candidate and not _is_lowest_make(candidate):
                selected_make = candidate
        if (not selected_make or _is_lowest_make(selected_make)) and selection.get("rate_master_id"):
            try:
                from apps.database_manager.models import Rate_Master_Output

                rm_row = Rate_Master_Output.objects.filter(pk=int(selection["rate_master_id"])).first()
                if rm_row and rm_row.Make:
                    selected_make = str(rm_row.Make).strip()
            except Exception:
                pass

        selected_vendor = str(
            product.get("selected_vendor")
            or selection.get("vendor")
            or ""
        ).strip()
        if not selected_vendor:
            candidate_vendor = str(
                (rate_detail or {}).get("vendor")
                or (rate_detail or {}).get("Vendor")
                or selection.get("vendor")
                or ""
            ).strip()
            if candidate_vendor:
                selected_vendor = candidate_vendor

        make_source = str(
            product.get("selected_make_source")
            or selection.get("make_source")
            or ""
        ).strip().lower()

        selected_approved_make = ""
        selected_available_make = ""
        if selected_make and not _is_lowest_make(selected_make):
            in_available = _make_in_options(selected_make, available_make_options)
            in_approved = _make_in_options(selected_make, approved_make_options)

            if not approved_make_options:
                selected_available_make = _align_option_label(selected_make, available_make_options) or (
                    selected_make if in_available else ""
                )
                make_source = "available"
            elif make_source == "available":
                if in_available:
                    selected_available_make = _align_option_label(selected_make, available_make_options)
                elif in_approved:
                    selected_approved_make = _align_option_label(selected_make, approved_make_options)
            elif make_source == "approved":
                if in_approved:
                    selected_approved_make = _align_option_label(selected_make, approved_make_options)
                elif in_available:
                    selected_available_make = _align_option_label(selected_make, available_make_options)
            else:
                if in_approved:
                    selected_approved_make = _align_option_label(selected_make, approved_make_options)
                elif in_available:
                    selected_available_make = _align_option_label(selected_make, available_make_options)
                elif available_make_options and not approved_make_options:
                    selected_available_make = _align_option_label(selected_make, available_make_options)

        all_vendor_options: list[str] = []
        seen_vendors: set[str] = set()
        for v in vendor_options:
            text = (v or "").strip()
            if text and text not in seen_vendors:
                seen_vendors.add(text)
                all_vendor_options.append(text)
        for vendors in vendors_by_make.values():
            for vendor in vendors or []:
                text = (vendor or "").strip()
                if not text or text in seen_vendors:
                    continue
                seen_vendors.add(text)
                all_vendor_options.append(text)

        active_make = selected_available_make or selected_approved_make or selected_make
        if active_make and not _is_lowest_make(active_make):
            vendor_options = list(vendors_by_make.get(active_make) or all_vendor_options)
        else:
            vendor_options = list(all_vendor_options)

        category = str(product.get("category") or "").strip()
        sub_category = str(product.get("sub_category") or "").strip()
        approved = approved_make_options
        source = str(product.get("vendor_selection_source") or "").strip()
        match_status = str(selection.get("status") or "not_searched").strip() or "not_searched"
        notes = str(selection.get("notes") or "")

        # Resolve whether make-list approved makes exist for this product taxonomy.
        stored_approved = product.get("approved_make_found")
        if stored_approved is None:
            approved_make_found = True if not self.has_make_list else bool(approved)
        else:
            approved_make_found = bool(stored_approved)

        # Manual typed make/vendor (not-found override) counts as filtered, not not_found.
        is_not_available = is_product_not_available(product) or (
            match_status == NOT_AVAILABLE_STATUS
            or source == NOT_AVAILABLE_SOURCE
            or not loaded_catalog_product_id(product)
        )
        if is_not_available:
            make_status = "not_available"
            approved_make_found = False
        elif source == "manual" and (selected_make or selected_vendor or match_status != "not_searched"):
            make_status = "filtered"
            approved_make_found = True
        elif (
            source == "not_found"
            or notes == NO_APPROVED_MAKE_LABEL
            or (
                self.has_make_list
                and not approved
                and not selected_make
                and match_status != "matched"
            )
        ):
            # not_found = no approved makes for category/sub-category in the make list.
            make_status = "not_found"
            approved_make_found = False
        elif source == "manual":
            make_status = "filtered"
        else:
            make_status = "default"

        # True when Product Id exists but Rate_Master_Output row was not found.
        is_no_match = (
            not is_not_available
            and make_status != "not_found"
            and match_status == "unmatched"
        )
        # Use dropdowns whenever approved or available options exist.
        allow_typed_make_vendor = False if is_not_available else (not bool(approved_make_options or available_make_options))

        same_price_choices = list(selection.get("same_price_choices") or [])
        same_price_tie = bool(selection.get("same_price_tie")) and bool(same_price_choices)
        if same_price_tie and not notes:
            notes = SAME_PRICE_TIE_LABEL

        qty_fields = quantity_display_fields(
            {
                **product,
                "quantity": product.get("quantity")
                if product.get("quantity") not in (None, "")
                else qty,
                "quantity_unit": product.get("quantity_unit")
                if product.get("quantity_unit") not in (None, "")
                else unit,
            }
        )

        if is_not_available:
            status_label = NOT_AVAILABLE_LABEL
        elif make_status == "not_found":
            status_label = NOT_LISTED_LABEL
        elif is_no_match:
            status_label = NOT_IN_DB_LABEL
        elif match_status in ("matched", "pending") or rate_detail:
            status_label = "Matched"
        else:
            status_label = "Select make"

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
            "qty": qty_fields["quantity"],
            **qty_fields,
            "approved_make_options": [] if is_not_available else approved_make_options,
            "approved_make_options_json": json.dumps([] if is_not_available else approved_make_options),
            "available_make_options": [] if is_not_available else available_make_options,
            "available_make_options_json": json.dumps([] if is_not_available else available_make_options),
            "has_approved_makes": bool(approved_make_options) and not is_not_available,
            "selected_approved_make": selected_approved_make if not is_not_available else "",
            "selected_available_make": selected_available_make if not is_not_available else "",
            "make_options": [] if is_not_available else (approved_make_options or available_make_options),
            "make_options_json": json.dumps([] if is_not_available else (approved_make_options or available_make_options)),
            "vendor_options": [] if is_not_available else vendor_options,
            "vendor_options_json": json.dumps([] if is_not_available else all_vendor_options),
            "vendors_by_make": {} if is_not_available else vendors_by_make,
            "vendors_by_make_json": json.dumps({} if is_not_available else vendors_by_make),
            "makes_by_vendor": {} if is_not_available else makes_by_vendor,
            "makes_by_vendor_json": json.dumps({} if is_not_available else makes_by_vendor),
            "selected_make": selected_make if not is_not_available else "",
            "selected_make_source": make_source,
            "selected_vendor": selected_vendor if not is_not_available else "",
            "match_status": match_status,
            "status_label": status_label,
            "confidence": selection.get("confidence"),
            "tech_key": selection.get("tech_key") or "",
            "rate_master_id": selection.get("rate_master_id"),
            "catalog_product_id": _catalog_product_id({**product, "vendor_selection": selection}),
            "rate_id": (
                ""
                if is_not_available
                else str(
                    selection.get("rate_id")
                    or (rate_detail or {}).get("rate_id")
                    or ""
                ).strip()
            ),
            "matched_summary": selection.get("summary") or "",
            "rate_detail": None if is_not_available else rate_detail,
            "labour_detail": None if is_not_available else labour_detail,
            "line_output": line_output,
            "notes": notes,
            "make_status": make_status,
            "approved_make_found": approved_make_found,
            "highlight_no_make": make_status == "not_found",
            "is_not_available": is_not_available,
            "is_no_match": is_no_match,
            "show_manual_apply": (
                not is_not_available
                and (
                    make_status == "not_found"
                    or is_no_match
                    or same_price_tie
                    or bool(same_price_choices)
                )
            ),
            "allow_typed_make_vendor": allow_typed_make_vendor,
            "vendor_rate_review": False,
            "same_price_tie": same_price_tie if not is_not_available else False,
            "same_price_choices": same_price_choices if not is_not_available else [],
            "same_price_choices_json": json.dumps(
                same_price_choices if not is_not_available else []
            ),
        }

