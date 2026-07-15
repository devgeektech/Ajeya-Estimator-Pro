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
from apps.boq.services.boq_extraction_service import BOQExtractionService
from apps.boq.services.boq_extract_service import load_extract_data
from apps.boq.services.boq_row_grouping_service import full_description_for_row, resolve_anchor_row_id
from apps.boq.services.make_list_constraint_service import MakeListConstraintService, walk_rows_tree
from apps.boq.services.product_matching_service import ProductMatchingService
from apps.boq.services.serial_normalizer import structure_for_analysis
from apps.database_manager.services.activation import get_active_database_version
from common.choices import BOQStatus
from common.exceptions import AIServiceError, BOQAIError, ValidationError

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
        stats["rows_total"] += 1
        if row.get("skip_matching"):
            stats["rows_skipped"] += 1
        stats["products_total"] += len(row.get("products") or [])
        stats["activities_total"] += len(row.get("activities") or [])
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
        stats["activities_total"] += len(row.get("activities") or [])
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
        """AI-only step: extract products and activities from BOQ rows."""
        boq = self._get_boq()
        self._set_status(boq, BOQStatus.PROCESSING)
        try:
            boq_payload, _make_list_payload = load_extract_data(boq)
            boq_data = structure_for_analysis(boq_payload)
            extraction = BOQExtractionService(boq_data).extract()
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
            }
            self._persist_analysis(boq, analysis_payload, BOQStatus.EXTRACTED)
            logger.info("BOQ extraction completed for id=%s (%s)", boq.pk, boq.boq_name)
            return analysis_payload
        except Exception as exc:
            logger.exception("BOQ extraction failed for id=%s", boq.pk)
            self._set_status(boq, BOQStatus.ANALYSIS_FAILED)
            if isinstance(exc, (AIServiceError, BOQAIError)):
                raise
            raise BOQAIError(f"BOQ extraction failed: {exc}") from exc

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
        """Match extracted products/activities against the active master database."""
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
                "rows": analyzed_rows,
            }
            self._persist_analysis(boq, analysis_payload, BOQStatus.PROCESSED)
            logger.info("BOQ matching completed for id=%s (%s)", boq.pk, boq.boq_name)
            return analysis_payload
        except Exception as exc:
            logger.exception("BOQ matching failed for id=%s", boq.pk)
            self._set_status(boq, BOQStatus.ANALYSIS_FAILED)
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
        approved_makes = make_list_service.approved_makes_for_description(description)
        stored_options = list(row_make_list.get("approved_makes") or [])
        if prefer_lowest_price:
            approved_makes = stored_options or approved_makes or make_list_service.all_approved_makes()
        elif selected_make:
            approved_makes = [selected_make]

        product_matches: list[dict[str, Any]] = []
        for product in row.get("products") or []:
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
        save_boq_analysis_json(boq.boq_name, analysis_payload)
        analysis_payload["analysis_json_path"] = analysis_json_relative_path(boq.boq_name)
        if analysis_payload.get("phase") == PHASE_MATCHED:
            match_payload = build_match_results_payload(analysis_payload)
            save_boq_match_results_json(boq.boq_name, match_payload)
            analysis_payload["match_results_json_path"] = match_results_json_relative_path(boq.boq_name)
        boq.analysis_data = analysis_payload
        boq.status = status
        boq.save(update_fields=["analysis_data", "status"])

    @staticmethod
    def _set_status(boq: BOQ, status: str) -> None:
        with transaction.atomic():
            boq.status = status
            boq.save(update_fields=["status"])
