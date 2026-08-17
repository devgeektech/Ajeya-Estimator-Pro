"""Make & vendor selection after Analysis — exact Rate_Master_Output match + rates."""
from __future__ import annotations

import logging
from typing import Any

from common.db import atomic

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_store import save_boq_analysis_json
from apps.boq.services.boq_extraction_service import normalize_product_fields
from apps.boq.services.boq_line_output_service import BOQLineOutputService
from apps.boq.services.boq_row_fields import (
    QTY_KEYS as _QTY_KEYS,
    field_from_map as _field_from_map,
    ordered_boq_rows as _ordered_boq_rows,
)
from apps.boq.services.labour_detail_retrieval_service import LabourDetailRetrievalService
from apps.boq.services.make_list_constraint_service import MakeListConstraintService
from apps.boq.services.make_vendor_cascade import MakeVendorCascadeMixin
from apps.boq.services.make_vendor_common import (
    _catalog_product_id,
    _is_lowest_make,
    _product_summary,
)
from apps.boq.services.make_vendor_display import MakeVendorDisplayMixin
from apps.boq.services.make_vendor_rates import MakeVendorRatesMixin
from apps.boq.services.product_matching_service import structured_match_score
from apps.boq.services.rate_detail_retrieval_service import RateDetailRetrievalService
from apps.boq.services.serial_normalizer import analysis_fields
from apps.database_manager.models import Rate_Master_Output
from apps.database_manager.services.activation import get_active_database_version
from common.choices import BOQStatus
from common.constants import MATCH_CONFIDENCE_THRESHOLD
from common.exceptions import BOQAIError, ValidationError
from utils.json_safe import json_safe
from utils.timestamps import now_local_iso

logger = logging.getLogger("boq_ai")


class MakeVendorSelectionService(
    MakeVendorDisplayMixin,
    MakeVendorCascadeMixin,
    MakeVendorRatesMixin,
):
    """
    After Analysis, an expert picks Make + Vendor, searches Rate_Master_Output,
    and loads labour by Product_ID.

    Display / cascade / rates internals live in sibling mixin modules; public
    method names on this class are unchanged for views.
    """


    def __init__(self, boq_id: int, make_list_data: dict | None = None):
        self.boq_id = boq_id
        self.make_list_service = MakeListConstraintService(make_list_data)
        # In-memory Rate_Master_Output index for display builds (avoids N+1 queries).
        self._rate_index_version_id: int | None = None
        self._rates_by_category: dict[str, list[dict[str, str]]] = {}


    @property
    def has_make_list(self) -> bool:
        """True when an uploaded make list provides approved-make constraints."""
        return bool(self.make_list_service.has_constraints)


    def select_and_match(
        self,
        *,
        row_id: str,
        product_index: int,
        make: str,
        vendor: str = "",
        preview_only: bool = False,
    ) -> dict[str, Any]:
        """Persist make/vendor, find a rate row, and load labour by Product_ID.

        When ``preview_only`` is True (Not found / No match before Apply), return
        the rate lookup without writing analysis — the card stays red until Apply.
        """
        boq = self._get_boq()
        self._ensure_editable(boq)

        make_text = str(make or "").strip()
        vendor_text = str(vendor or "").strip()
        if not make_text and not vendor_text:
            raise ValidationError("Select a make or vendor before searching.")

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
        # Make-list gap: expert may type make/vendor and search Rate_Master_Output.
        allow_manual_override = self.has_make_list and not approved_makes
        prefer_lowest = _is_lowest_make(make_text) or (not make_text and not vendor_text)
        # A concrete make picked by the expert comes from the product's Rate_Master
        # options, so it is honoured even when the make list does not list it.
        expert_make = bool(make_text) and not prefer_lowest
        if expert_make and approved_makes and not MakeListConstraintService.make_is_allowed(
            make_text, approved_makes
        ):
            logger.info(
                "Make %s not in make list for %s / %s — keeping expert selection",
                make_text,
                category,
                sub_category,
            )
        if allow_manual_override and prefer_lowest:
            raise ValidationError(
                "Enter a make (and optional vendor) — no approved make in the make list."
            )
        if _is_lowest_make(vendor_text):
            vendor_text = ""
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
            vendor=vendor_text,
            quantity=qty,
            database_version_id=database_version_id,
            prefer_lowest_price=prefer_lowest or (bool(make_text) and not vendor_text),
            # Expert-chosen make is its own filter; approved list only guides defaults.
            approved_makes=None if (allow_manual_override or expert_make) else approved_makes,
        )

        if preview_only:
            # Rate preview for Not found / No match — Apply commits the match.
            logger.debug(
                "Make/vendor rate preview boq=%s row=%s product=%s make=%s vendor=%s status=%s",
                boq.pk,
                row_id,
                product_index,
                make_text,
                vendor_text,
                match_payload.get("status"),
            )
            return match_payload

        updated = dict(product)
        updated["selected_make"] = match_payload.get("make") or make_text or None
        updated["selected_vendor"] = (
            match_payload.get("vendor")
            or vendor_text
            or None
        )
        updated["make_hint"] = make_text or updated.get("make_hint")
        updated["vendor_selection"] = match_payload
        if match_payload.get("product_id"):
            updated["catalog_product_id"] = str(match_payload.get("product_id")).strip()
        # Manual override leaves the not-found bucket even when the make list has no entry.
        updated["approved_make_found"] = True if (
            allow_manual_override or not self.has_make_list or bool(approved_makes)
        ) else False
        updated["vendor_selection_source"] = "manual"

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

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.debug(
            "Make/vendor selection saved boq=%s row=%s product=%s make=%s vendor=%s status=%s",
            boq.pk,
            row_id,
            product_index,
            make_text,
            vendor_text,
            match_payload.get("status"),
        )
        return match_payload

    def apply_manual_selection(
        self,
        *,
        row_id: str,
        product_index: int,
        make: str,
        vendor: str = "",
    ) -> dict[str, Any]:
        """Accept expert make/vendor on Not found / No match cards → green matched.

        Tries Rate_Master lookup first. If no row is found, still persists the
        typed/selected make+vendor as a manual matched selection so the card
        leaves the red not-found / no-match state.
        """
        boq = self._get_boq()
        self._ensure_editable(boq)

        make_text = str(make or "").strip()
        vendor_text = str(vendor or "").strip()
        if _is_lowest_make(make_text):
            make_text = ""
        if _is_lowest_make(vendor_text):
            vendor_text = ""
        if not make_text:
            raise ValidationError("Enter or select a make before applying.")

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
            vendor=vendor_text,
            quantity=(
                product.get("quantity")
                if product.get("quantity") not in (None, "")
                else qty
            ),
            database_version_id=database_version_id,
            prefer_lowest_price=False,
            approved_makes=None,
        )

        applied_make = str(match_payload.get("make") or make_text).strip()
        applied_vendor = str(match_payload.get("vendor") or vendor_text).strip()
        if match_payload.get("status") != "matched":
            # Force-accept manual make/vendor when Rate_Master has no row.
            prior = dict(product.get("vendor_selection") or {})
            rate_detail = match_payload.get("rate_detail") or prior.get("rate_detail")
            labour_detail = match_payload.get("labour_detail") or prior.get("labour_detail")
            line_output = match_payload.get("line_output") or BOQLineOutputService.build(
                quantity=(
                    product.get("quantity")
                    if product.get("quantity") not in (None, "")
                    else qty
                ),
                rate_detail=rate_detail,
                labour_detail=labour_detail,
                is_pending=not bool(rate_detail),
                rate_only=bool(product.get("rate_only")),
            )
            match_payload = {
                **match_payload,
                "status": "matched",
                "confidence": 100.0,
                "make": applied_make,
                "vendor": applied_vendor,
                "rate_detail": rate_detail,
                "labour_detail": labour_detail,
                "line_output": line_output,
                "notes": (
                    "Manually applied make/vendor "
                    "(no Rate_Master_Output row for this combination)."
                ),
                "prefer_lowest_price": False,
                "matched_at": now_local_iso(),
            }
        else:
            match_payload["make"] = applied_make or match_payload.get("make")
            match_payload["vendor"] = applied_vendor or match_payload.get("vendor")

        catalog_id = str(
            match_payload.get("catalog_product_id")
            or match_payload.get("product_id")
            or _catalog_product_id(product)
            or ""
        ).strip()
        if catalog_id:
            match_payload["product_id"] = catalog_id
            match_payload["catalog_product_id"] = catalog_id

        updated = dict(product)
        updated["selected_make"] = applied_make or None
        updated["selected_vendor"] = applied_vendor or None
        if applied_make:
            updated["make_hint"] = applied_make
        updated["vendor_selection"] = match_payload
        if catalog_id:
            updated["catalog_product_id"] = catalog_id
        updated["approved_make_found"] = True
        updated["vendor_selection_source"] = "manual"

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

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.info(
            "Manual make/vendor applied boq=%s row=%s product=%s make=%s vendor=%s "
            "rate_matched=%s",
            boq.pk,
            row_id,
            product_index,
            applied_make,
            applied_vendor,
            bool(match_payload.get("rate_master_id")),
        )
        return match_payload


    def resolve_same_price_choice(
        self,
        *,
        row_id: str,
        product_index: int,
        rate_master_id: int,
    ) -> dict[str, Any]:
        """Expert picks one Rate_Master_Output row when lowest price ties."""
        boq = self._get_boq()
        self._ensure_editable(boq)

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

        selection = dict(product.get("vendor_selection") or {})
        choices = list(selection.get("same_price_choices") or [])
        chosen = next(
            (
                item
                for item in choices
                if int(item.get("rate_master_id") or 0) == int(rate_master_id)
            ),
            None,
        )
        if chosen is None:
            raise ValidationError("Selected same-price option is no longer available.")

        try:
            rate = Rate_Master_Output.objects.get(
                pk=int(rate_master_id),
                database_version_id=database_version_id,
            )
        except Rate_Master_Output.DoesNotExist as exc:
            raise ValidationError("Rate_Master_Output row not found for this choice.") from exc

        boq_row = next(
            (
                item
                for item in _ordered_boq_rows(boq.boq_data or {})
                if str(item.get("row_id")) == str(row_id)
            ),
            {},
        )
        qty = _field_from_map(analysis_fields(boq_row), _QTY_KEYS)
        extracted = normalize_product_fields(dict(product))
        qty_value = (
            extracted.get("quantity")
            if extracted.get("quantity") not in (None, "")
            else qty
        )

        rate_service = RateDetailRetrievalService(database_version_id)
        labour_service = LabourDetailRetrievalService(database_version_id)
        rate_detail = rate_service.get_by_id(rate.pk)
        labour_detail = labour_service.get_by_product_id(rate.Product_ID)
        structured, breakdown = structured_match_score(extracted, rate)
        status = "matched" if structured >= MATCH_CONFIDENCE_THRESHOLD else "pending"
        line_output = BOQLineOutputService.build(
            quantity=qty_value,
            rate_detail=rate_detail,
            labour_detail=labour_detail,
            is_pending=status != "matched",
            rate_only=bool(extracted.get("rate_only")),
        )
        match_payload = {
            "make": str(rate.Make or chosen.get("make") or "").strip(),
            "vendor": str(rate.Vendor or chosen.get("vendor") or "").strip(),
            "status": status,
            "confidence": round(float(structured), 2),
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
            "notes": "",
            "prefer_lowest_price": bool(selection.get("prefer_lowest_price")),
            "same_price_tie": False,
            "same_price_choices": choices,
            "same_price_resolved": True,
            "matched_at": now_local_iso(),
        }

        updated = dict(product)
        updated["selected_make"] = match_payload["make"] or None
        updated["selected_vendor"] = match_payload["vendor"] or None
        if match_payload["make"]:
            updated["make_hint"] = match_payload["make"]
        updated["vendor_selection"] = match_payload
        updated["vendor_selection_source"] = "manual"
        updated["approved_make_found"] = True

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

        with atomic():
            safe = json_safe(analysis)
            save_boq_analysis_json(boq.boq_name, safe)
            boq.analysis_data = safe
            boq.save(update_fields=["analysis_data"])

        logger.debug(
            "Same-price choice resolved boq=%s row=%s product=%s rate_master_id=%s vendor=%s",
            boq.pk,
            row_id,
            product_index,
            rate.pk,
            match_payload.get("vendor"),
        )
        return match_payload


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

