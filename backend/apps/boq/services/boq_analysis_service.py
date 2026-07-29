"""Orchestrate BOQ extraction, matching, and analysis persistence."""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_enrichment_service import BOQAnalysisEnrichmentService
from apps.boq.services.boq_analysis_store import (
    analysis_json_relative_path,
    build_match_results_payload,
    match_results_json_relative_path,
    save_boq_analysis_json,
    save_boq_match_results_json,
)
from apps.boq.services.boq_extraction_service import BOQExtractionService, _normalize_product_fields
from apps.boq.services.boq_extract_service import load_extract_data
from apps.boq.services.boq_job_progress import (
    clear_boq_job_progress,
    set_boq_job_progress,
)
from apps.boq.services.boq_row_grouping_service import full_description_for_row, resolve_anchor_row_id
from apps.boq.services.make_list_constraint_service import MakeListConstraintService, walk_rows_tree
from apps.boq.services.product_ai_mapping_service import ProductAIMappingService
from apps.boq.services.product_attribute_enrichment_service import product_needs_attribute_enrichment
from apps.boq.services.product_matching_service import ProductMatchingService
from apps.boq.services.serial_normalizer import structure_for_analysis
from apps.database_manager.services.activation import get_active_database_version
from common.choices import BOQStatus
from common.exceptions import AIServiceError, BOQAIError, ValidationError
from utils.json_safe import json_safe

logger = logging.getLogger("boq_ai")

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
PHASE_EXTRACTED = "extracted"
PHASE_MATCHED = "matched"


def _row_description(boq_data: dict, row_id: str) -> str:
    full_text = full_description_for_row(boq_data, row_id)
    if full_text:
        return full_text
    tree = boq_data.get("rows_tree") or []
    for node in walk_rows_tree(tree):
        if node.get("row_id") != row_id:
            continue
        fields = node.get("fields") or {}
        for key in _DESCRIPTION_KEYS:
            value = fields.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return ""


def _row_order(boq_payload: dict, extraction: dict) -> list[str]:
    row_order = [
        str(row.get("row_id"))
        for row in (boq_payload.get("rows") or [])
        if row.get("row_id")
    ]
    if row_order:
        return row_order
    return [
        str(row.get("row_id"))
        for row in extraction.get("rows") or []
        if row.get("row_id")
    ]


def _compute_extraction_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "rows_total": 0,
        "rows_skipped": 0,
        "products_total": 0,
        "activities_total": 0,
    }
    for row in rows:
        row["activities"] = []
        stats["rows_total"] += 1
        if row.get("skip_matching"):
            stats["rows_skipped"] += 1
        stats["products_total"] += len(row.get("products") or [])
    return stats


def _compute_match_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "rows_total": 0,
        "rows_skipped": 0,
        "products_total": 0,
        "products_matched": 0,
        "products_pending": 0,
        "activities_total": 0,
    }
    for row in rows:
        stats["rows_total"] += 1
        if row.get("skip_matching"):
            stats["rows_skipped"] += 1
            continue
        product_matches = row.get("product_matches") or []
        if product_matches:
            for item in product_matches:
                stats["products_total"] += 1
                match = item.get("match") or {}
                if match.get("status") == "matched":
                    stats["products_matched"] += 1
                else:
                    stats["products_pending"] += 1
        else:
            product_count = len(row.get("products") or [])
            stats["products_total"] += product_count
            stats["products_pending"] += product_count
    return stats


def _replace_rows(
    existing_rows: list[dict[str, Any]],
    replacements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    replacement_map = {
        str(row.get("row_id")): row for row in replacements if row.get("row_id")
    }
    updated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in existing_rows:
        row_id = str(row.get("row_id") or "")
        if row_id in replacement_map:
            updated.append(replacement_map[row_id])
            seen.add(row_id)
        else:
            updated.append(row)
    for row_id, row in replacement_map.items():
        if row_id not in seen:
            updated.append(row)
    return updated


class BOQAnalysisService:
    """Run BOQ extraction and matching as separate pipeline steps."""

    def __init__(self, boq_id: int):
        self.boq_id = boq_id

    def run_extraction(self) -> dict[str, Any]:
        """Extract products, then enrich attributes from Rate_Master."""
        boq = self._get_boq()
        self._set_status(boq, BOQStatus.PROCESSING)
        set_boq_job_progress(boq.pk, percent=2, label="Starting analysis…", phase="extract")
        try:
            boq_payload, _make_list_payload = load_extract_data(boq)
            boq_data = structure_for_analysis(boq_payload)
            set_boq_job_progress(boq.pk, percent=8, label="Extracting products…", phase="extract")

            def _on_extract_progress(done: int, total: int) -> None:
                total = max(total, 1)
                # Extraction covers roughly 8% → 55%.
                percent = 8 + int((done / total) * 47)
                set_boq_job_progress(
                    boq.pk,
                    percent=percent,
                    label=f"Extracting products ({done}/{total})…",
                    phase="extract",
                )

            extraction = BOQExtractionService(boq_data).extract(
                progress_callback=_on_extract_progress,
            )
            extraction_by_row = {
                str(row.get("row_id")): row
                for row in extraction.get("rows") or []
                if row.get("row_id")
            }

            extracted_rows: list[dict[str, Any]] = []
            for row_id in _row_order(boq_payload, extraction):
                row = extraction_by_row.get(row_id)
                if not row:
                    continue
                extracted_rows.append({**row, "product_matches": []})

            set_boq_job_progress(
                boq.pk,
                percent=55,
                label="Matching products to database…",
                phase="extract",
            )

            def _on_enrich_progress(done: int, total: int) -> None:
                total = max(total, 1)
                # First matching pass covers roughly 55% → 78%.
                percent = 55 + int((done / total) * 23)
                set_boq_job_progress(
                    boq.pk,
                    percent=percent,
                    label=f"Matching products to database ({done}/{total})…",
                    phase="extract",
                )

            extracted_rows = self._enrich_extracted_attributes(
                extracted_rows,
                progress_callback=_on_enrich_progress,
            )

            set_boq_job_progress(
                boq.pk,
                percent=80,
                label="Refining product matches…",
                phase="extract",
            )

            def _on_refine_progress(done: int, total: int) -> None:
                total = max(total, 1)
                # Refine passes cover roughly 80% → 95% (same path as Re-analyse).
                percent = 80 + int((done / total) * 15)
                set_boq_job_progress(
                    boq.pk,
                    percent=percent,
                    label=f"Refining product matches ({done}/{total})…",
                    phase="extract",
                )

            extracted_rows = self._refine_extracted_matches(
                extracted_rows,
                progress_callback=_on_refine_progress,
            )

            set_boq_job_progress(boq.pk, percent=98, label="Saving results…", phase="extract")
            analysis_payload = {
                "schema_version": 2,
                "phase": PHASE_EXTRACTED,
                "boq_id": boq.pk,
                "boq_name": boq.boq_name,
                "stats": _compute_extraction_stats(extracted_rows),
                "extraction": {
                    "schema_version": extraction.get("schema_version"),
                    "row_count": extraction.get("row_count"),
                },
                "rows": extracted_rows,
                # Locked until Analysis → Next runs lowest-price prefills.
                "make_vendor_defaults_applied": False,
                "subcategory_make_selections": {},
            }
            self._persist_analysis(boq, analysis_payload, BOQStatus.EXTRACTED)
            set_boq_job_progress(boq.pk, percent=100, label="Analysis complete", phase="extract")
            logger.info("BOQ extraction completed for id=%s (%s)", boq.pk, boq.boq_name)
            self._audit(boq, "Analysed BOQ")
            self._notify_user(
                boq,
                "BOQ analysed",
                f"BOQ '{boq.boq_name}' analysis finished. Review products on the Analysis tab.",
            )
            return analysis_payload
        except Exception as exc:
            logger.exception("BOQ extraction failed for id=%s", boq.pk)
            set_boq_job_progress(boq.pk, percent=100, label="Analysis failed", phase="extract")
            self._set_status(boq, BOQStatus.ANALYSIS_FAILED)
            self._audit(boq, "Analysis failed")
            self._notify_user(
                boq,
                "BOQ analysis failed",
                f"BOQ '{boq.boq_name}' analysis failed. Open the BOQ to retry.",
            )
            if isinstance(exc, (AIServiceError, BOQAIError)):
                raise
            raise BOQAIError(f"BOQ extraction failed: {exc}") from exc
        finally:
            # Keep 100% briefly for the last poll, then clear on next request cycle.
            pass

    def rematch_row(
        self,
        row_id: str,
        product_index: int | None = None,
    ) -> dict[str, Any]:
        """
        Re-run DB candidate recall + AI mapping for one row using current products.

        Preserves expert-filled fields/attributes and rematches against Rate_Master
        (fill missing attrs → Re-analyse → better DB product). Does not re-extract
        from the BOQ workbook text.

        When ``product_index`` is set, only that product is rematched so other
        product cards on the same row stay interactive.
        """
        with transaction.atomic():
            try:
                boq = BOQ.objects.select_for_update().get(pk=self.boq_id)
            except BOQ.DoesNotExist:
                raise BOQAIError(f"BOQ id={self.boq_id} not found.") from None

            existing = dict(boq.analysis_data or {})
            rows = list(existing.get("rows") or [])
            if not rows:
                raise ValidationError("Run Analyse first to extract products from this BOQ.")
            if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
                raise ValidationError("Wait for the current job to finish.")

            target = next(
                (row for row in rows if str(row.get("row_id")) == str(row_id)),
                None,
            )
            if target is None:
                raise ValidationError(f"Unknown BOQ row: {row_id}")
            if not (target.get("products") or []):
                # No products yet — fall back to full re-extract from workbook text.
                # Release lock before long extract by ending this block via call outside.
                pass
            else:
                previous_status = boq.status
                try:
                    target = dict(target)
                    products = [
                        _normalize_product_fields(product)
                        for product in (target.get("products") or [])
                    ]
                    if product_index is not None:
                        want = int(product_index)
                        selected = next(
                            (
                                product
                                for product in products
                                if int(product.get("product_index", -1)) == want
                            ),
                            None,
                        )
                        if selected is None:
                            raise ValidationError(f"Unknown product index: {product_index}")
                        stub = {**target, "products": [selected]}
                        rematched = self._enrich_extracted_attributes([stub])
                        rematched = self._refine_extracted_matches(rematched)
                        updated_product = (rematched[0].get("products") or [selected])[0]
                        merged_products = []
                        for product in products:
                            if int(product.get("product_index", -1)) == want:
                                merged_products.append(updated_product)
                            else:
                                merged_products.append(product)
                        target["products"] = merged_products
                        rematched_rows = [target]
                    else:
                        target["products"] = products
                        rematched_rows = self._enrich_extracted_attributes([target])
                        rematched_rows = self._refine_extracted_matches(rematched_rows)

                    updated_rows = _replace_rows(rows, rematched_rows)
                    analysis_payload = {
                        **existing,
                        "schema_version": 2,
                        "phase": PHASE_EXTRACTED,
                        "boq_id": boq.pk,
                        "boq_name": boq.boq_name,
                        "stats": _compute_extraction_stats(updated_rows),
                        "extraction": {
                            **(existing.get("extraction") or {}),
                            "last_row_rematch": str(row_id),
                            "last_product_rematch": product_index,
                        },
                        "rows": updated_rows,
                    }
                    # Do not flip the BOQ to PROCESSING (blocks autosave on other cards).
                    self._persist_analysis(boq, analysis_payload, BOQStatus.EXTRACTED)
                    logger.info(
                        "BOQ row rematch completed for id=%s row=%s product=%s",
                        boq.pk,
                        row_id,
                        product_index,
                    )
                    return analysis_payload
                except Exception as exc:
                    logger.exception(
                        "BOQ row rematch failed for id=%s row=%s", boq.pk, row_id
                    )
                    self._set_status(
                        boq, previous_status if previous_status else BOQStatus.ANALYSIS_FAILED
                    )
                    if isinstance(exc, (AIServiceError, BOQAIError, ValidationError)):
                        raise
                    raise BOQAIError(f"BOQ row rematch failed: {exc}") from exc

        # Empty-products path: re-extract outside the rematch lock scope above.
        return self.re_extract_row(row_id)

    def re_extract_row(self, row_id: str) -> dict[str, Any]:
        """Re-run AI extraction for one anchor group and merge into analysis_data."""
        boq = self._get_boq()
        existing = dict(boq.analysis_data or {})
        if not existing.get("rows"):
            raise ValidationError("Run Analyse first to extract products from this BOQ.")
        if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
            raise ValidationError("Wait for the current job to finish.")

        previous_status = boq.status
        self._set_status(boq, BOQStatus.PROCESSING)
        try:
            boq_payload, _make_list_payload = load_extract_data(boq)
            boq_data = structure_for_analysis(boq_payload)
            extraction = BOQExtractionService(boq_data).extract_anchor(row_id)
            anchor_id = str(extraction.get("anchor_row_id") or row_id)

            replacements: list[dict[str, Any]] = []
            for row in extraction.get("rows") or []:
                existing_row = next(
                    (
                        item
                        for item in (existing.get("rows") or [])
                        if str(item.get("row_id")) == str(row.get("row_id"))
                    ),
                    {},
                )
                make_list = existing_row.get("make_list") if str(row.get("row_id")) == anchor_id else None
                replacement = {
                    **row,
                    "product_matches": [],
                }
                if make_list:
                    replacement["make_list"] = make_list
                replacements.append(replacement)

            replacements = self._enrich_extracted_attributes(replacements)
            replacements = self._refine_extracted_matches(replacements)
            updated_rows = _replace_rows(list(existing.get("rows") or []), replacements)
            analysis_payload = {
                **existing,
                "schema_version": 2,
                "phase": PHASE_EXTRACTED,
                "boq_id": boq.pk,
                "boq_name": boq.boq_name,
                "stats": _compute_extraction_stats(updated_rows),
                "extraction": {
                    **(existing.get("extraction") or {}),
                    "schema_version": extraction.get("schema_version"),
                    "last_row_reextract": anchor_id,
                },
                "rows": updated_rows,
            }
            self._persist_analysis(boq, analysis_payload, BOQStatus.EXTRACTED)
            logger.info("BOQ row re-extraction completed for id=%s row=%s", boq.pk, anchor_id)
            return analysis_payload
        except Exception as exc:
            logger.exception("BOQ row re-extraction failed for id=%s row=%s", boq.pk, row_id)
            self._set_status(boq, previous_status if previous_status else BOQStatus.ANALYSIS_FAILED)
            if isinstance(exc, (AIServiceError, BOQAIError, ValidationError)):
                raise
            raise BOQAIError(f"BOQ row re-extraction failed: {exc}") from exc

    def run_matching(self) -> dict[str, Any]:
        """Match extracted products against the active master database."""
        boq = self._get_boq()
        existing = boq.analysis_data or {}
        if not existing.get("rows"):
            raise BOQAIError("Run Analyse first to extract products from this BOQ.")

        active_version = get_active_database_version()
        if active_version is None:
            raise BOQAIError("No active master database. Upload and activate a database first.")

        self._set_status(boq, BOQStatus.MATCHING)
        try:
            boq_payload, make_list_payload = load_extract_data(boq)
            boq_data = structure_for_analysis(boq_payload)
            make_list_data = structure_for_analysis(make_list_payload) if make_list_payload else {}
            make_list_service = MakeListConstraintService(make_list_data)
            matcher = ProductMatchingService(active_version.pk)

            extraction_by_row = {
                str(row.get("row_id")): row
                for row in existing.get("rows") or []
                if row.get("row_id")
            }

            analyzed_rows: list[dict[str, Any]] = []
            for row_id in _row_order(boq_payload, existing):
                row = extraction_by_row.get(row_id)
                if not row:
                    continue
                analyzed_rows.append(
                    self._match_one_row(
                        row,
                        boq_data=boq_data,
                        make_list_service=make_list_service,
                        matcher=matcher,
                    )
                )

            enricher = BOQAnalysisEnrichmentService(active_version.pk)
            analyzed_rows = enricher.enrich_rows(analyzed_rows)

            analysis_payload = {
                "schema_version": 2,
                "phase": PHASE_MATCHED,
                "boq_id": boq.pk,
                "boq_name": boq.boq_name,
                "database_version_id": active_version.pk,
                "stats": _compute_match_stats(analyzed_rows),
                "extraction": existing.get("extraction") or {},
                # Keep Make & Vendor unlock + cascade filters after Match.
                "make_vendor_defaults_applied": bool(
                    existing.get("make_vendor_defaults_applied")
                ),
                "subcategory_make_selections": existing.get("subcategory_make_selections")
                or {},
                # Match invalidates prior Calculate Price output.
                "pricing_ready": False,
                "row_pricing": {},
                "rows": analyzed_rows,
            }
            self._persist_analysis(boq, analysis_payload, BOQStatus.PROCESSED)
            logger.info("BOQ matching completed for id=%s (%s)", boq.pk, boq.boq_name)
            self._audit(boq, "Matched BOQ")
            self._notify_user(
                boq,
                "BOQ matched",
                f"BOQ '{boq.boq_name}' matching finished. Review Match Results.",
            )
            return analysis_payload
        except Exception as exc:
            logger.exception("BOQ matching failed for id=%s", boq.pk)
            self._set_status(boq, BOQStatus.ANALYSIS_FAILED)
            self._audit(boq, "Matching failed")
            self._notify_user(
                boq,
                "BOQ matching failed",
                f"BOQ '{boq.boq_name}' matching failed. Open the BOQ to retry.",
            )
            if isinstance(exc, (AIServiceError, BOQAIError)):
                raise
            raise BOQAIError(f"BOQ matching failed: {exc}") from exc

    def re_match_row(self, row_id: str) -> dict[str, Any]:
        """Re-run matching for one anchor row and merge into analysis_data."""
        boq = self._get_boq()
        existing = dict(boq.analysis_data or {})
        if not existing.get("rows"):
            raise ValidationError("Run Analyse first to extract products from this BOQ.")
        if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
            raise ValidationError("Wait for the current job to finish.")

        active_version = get_active_database_version()
        if active_version is None:
            raise ValidationError("No active master database. Upload and activate a database first.")

        previous_status = boq.status
        self._set_status(boq, BOQStatus.MATCHING)
        try:
            boq_payload, make_list_payload = load_extract_data(boq)
            boq_data = structure_for_analysis(boq_payload)
            make_list_data = structure_for_analysis(make_list_payload) if make_list_payload else {}
            make_list_service = MakeListConstraintService(make_list_data)
            matcher = ProductMatchingService(active_version.pk)
            anchor_id = resolve_anchor_row_id(boq_data, str(row_id))

            target = next(
                (
                    row
                    for row in (existing.get("rows") or [])
                    if str(row.get("row_id")) == anchor_id
                ),
                None,
            )
            if target is None:
                raise ValidationError(f"Unknown BOQ row: {anchor_id}")
            if target.get("skip_matching") and not (target.get("products") or []):
                raise ValidationError("This row has no products to match.")

            matched_row = self._match_one_row(
                target,
                boq_data=boq_data,
                make_list_service=make_list_service,
                matcher=matcher,
            )
            enricher = BOQAnalysisEnrichmentService(active_version.pk)
            matched_row = enricher.enrich_rows([matched_row])[0]

            updated_rows = _replace_rows(list(existing.get("rows") or []), [matched_row])
            analysis_payload = {
                **existing,
                "schema_version": 2,
                "phase": PHASE_MATCHED,
                "boq_id": boq.pk,
                "boq_name": boq.boq_name,
                "database_version_id": active_version.pk,
                "stats": _compute_match_stats(updated_rows),
                "extraction": existing.get("extraction") or {},
                "pricing_ready": False,
                "row_pricing": {},
                "rows": updated_rows,
            }
            self._persist_analysis(boq, analysis_payload, BOQStatus.PROCESSED)
            logger.info("BOQ row rematch completed for id=%s row=%s", boq.pk, anchor_id)
            return analysis_payload
        except Exception as exc:
            logger.exception("BOQ row rematch failed for id=%s row=%s", boq.pk, row_id)
            self._set_status(boq, previous_status if previous_status else BOQStatus.ANALYSIS_FAILED)
            if isinstance(exc, (AIServiceError, BOQAIError, ValidationError)):
                raise
            raise BOQAIError(f"BOQ row rematch failed: {exc}") from exc

    @staticmethod
    def _match_one_row(
        row: dict[str, Any],
        *,
        boq_data: dict[str, Any],
        make_list_service: MakeListConstraintService,
        matcher: ProductMatchingService,
    ) -> dict[str, Any]:
        row_id = str(row.get("row_id") or "")
        if row.get("skip_matching"):
            return {**row, "product_matches": []}

        description = _row_description(boq_data, row_id)
        row_make_list = row.get("make_list") or {}
        selected_make = row_make_list.get("selected_make")
        prefer_lowest_price = bool(row_make_list.get("prefer_lowest_price")) or (
            MakeListConstraintService.is_lowest_make_selection(selected_make)
        )
        if not make_list_service.has_constraints and not selected_make:
            prefer_lowest_price = True

        description_makes = make_list_service.approved_makes_for_description(description)
        stored_options = list(row_make_list.get("approved_makes") or [])

        product_matches: list[dict[str, Any]] = []
        for product in row.get("products") or []:
            # Prefer category-mapped approved makes for this product.
            category_makes = make_list_service.approved_makes_for_category(
                str(product.get("category") or ""),
                str(product.get("sub_category") or ""),
            )
            approved_makes = category_makes or description_makes
            if prefer_lowest_price:
                approved_makes = (
                    stored_options
                    or approved_makes
                    or make_list_service.all_approved_makes()
                )
            elif selected_make:
                approved_makes = [selected_make]

            product_for_match = dict(product)
            if (
                selected_make
                and not prefer_lowest_price
                and not product_for_match.get("make_hint")
            ):
                product_for_match["make_hint"] = selected_make
            match_result = matcher.match_product(
                product_for_match,
                approved_makes=approved_makes,
                prefer_lowest_price=prefer_lowest_price,
            )
            product_matches.append(
                {
                    "product_index": product.get("product_index", 0),
                    "extracted": product,
                    "match": match_result,
                }
            )
        return {**row, "product_matches": product_matches}

    @staticmethod
    def _enrich_extracted_attributes(
        rows: list[dict[str, Any]],
        progress_callback=None,
    ) -> list[dict[str, Any]]:
        """AI-map extracted products to Rate_Master + attribute schemas after extract."""
        active_version = get_active_database_version()
        if active_version is None:
            logger.warning("Attribute enrichment skipped: no active master database")
            return rows
        try:
            mapper = ProductAIMappingService(active_version.pk)
            return mapper.map_rows(rows, progress_callback=progress_callback)
        except Exception:
            logger.exception("AI product mapping failed; keeping AI-extracted attributes")
            return rows

    @staticmethod
    def _refine_extracted_matches(
        rows: list[dict[str, Any]],
        progress_callback=None,
    ) -> list[dict[str, Any]]:
        """
        Rematch like Analysis Re-analyse after first-pass taxonomy/schema alignment.

        1) Full rematch of every product (wider recall) — same path as Re-analyse
        2) Extra weak-only refine passes for remaining low-confidence products
        """
        active_version = get_active_database_version()
        if active_version is None:
            return rows
        try:
            mapper = ProductAIMappingService(active_version.pk)

            def _on_full(done: int, total: int) -> None:
                if not progress_callback:
                    return
                # First half of refine progress = full rematch.
                total = max(total, 1)
                progress_callback(done, total * 2)

            rematched = mapper.map_rows(
                rows,
                refine=True,
                progress_callback=_on_full,
            )

            def _on_weak(done: int, total: int) -> None:
                if not progress_callback:
                    return
                total = max(total, 1)
                progress_callback(total + done, total * 2)

            return mapper.refine_rows(
                rematched,
                passes=2,
                progress_callback=_on_weak,
            )
        except Exception:
            logger.exception("Product match refine failed; keeping first-pass matches")
            return rows

    def ensure_attribute_enrichment(self) -> bool:
        """
        Backfill DB product/attribute mapping for extracted products missing schema.

        Uses AI mapping when available (SQL/Chroma candidate recall + attribute map).
        """
        boq = self._get_boq()
        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        if not rows:
            return False
        if not any(
            product_needs_attribute_enrichment(product)
            for row in rows
            for product in (row.get("products") or [])
        ):
            return False

        active_version = get_active_database_version()
        if active_version is None:
            logger.warning("Attribute enrichment backfill skipped: no active master database")
            return False

        try:
            mapper = ProductAIMappingService(active_version.pk)
            updated_rows = mapper.map_rows(rows, only_missing=True)
        except Exception:
            logger.exception("AI product mapping backfill failed for BOQ id=%s", boq.pk)
            return False

        analysis["rows"] = updated_rows
        safe_analysis = json_safe(analysis)
        save_boq_analysis_json(boq.boq_name, safe_analysis)
        safe_analysis["analysis_json_path"] = analysis_json_relative_path(boq.boq_name)
        boq.analysis_data = safe_analysis
        boq.save(update_fields=["analysis_data"])
        logger.info("Backfilled AI product mappings for BOQ id=%s (%s)", boq.pk, boq.boq_name)
        return True

    def _get_boq(self) -> BOQ:
        try:
            return BOQ.objects.get(pk=self.boq_id)
        except BOQ.DoesNotExist:
            logger.error(
                "BOQ pipeline skipped: id=%s does not exist (deleted BOQ or stale Celery task)",
                self.boq_id,
            )
            raise BOQAIError(f"BOQ id={self.boq_id} not found.") from None

    def _persist_analysis(self, boq: BOQ, analysis_payload: dict[str, Any], status: str) -> None:
        # Strip Decimal/datetime so psycopg3 JSON dumps never fail.
        safe_payload = json_safe(analysis_payload)
        save_boq_analysis_json(boq.boq_name, safe_payload)
        safe_payload["analysis_json_path"] = analysis_json_relative_path(boq.boq_name)
        if safe_payload.get("phase") == PHASE_MATCHED:
            match_payload = json_safe(build_match_results_payload(safe_payload))
            save_boq_match_results_json(boq.boq_name, match_payload)
            safe_payload["match_results_json_path"] = match_results_json_relative_path(
                boq.boq_name
            )
        boq.analysis_data = safe_payload
        boq.status = status
        boq.save(update_fields=["analysis_data", "status"])

    @staticmethod
    def _set_status(boq: BOQ, status: str) -> None:
        with transaction.atomic():
            boq.status = status
            boq.save(update_fields=["status"])

    @staticmethod
    def _notify_user(boq: BOQ, title: str, message: str = "") -> None:
        from apps.notifications.services import notify

        notify(getattr(boq, "user", None), title, message)

    @staticmethod
    def _audit(boq: BOQ, action: str) -> None:
        from apps.audit.services import record

        record(getattr(boq, "user", None), action, "BOQ", boq.boq_name)
