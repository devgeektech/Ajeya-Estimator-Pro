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
from apps.boq.services.make_list_constraint_service import MakeListConstraintService, walk_rows_tree
from apps.boq.services.product_matching_service import ProductMatchingService
from apps.boq.services.serial_normalizer import structure_for_analysis
from apps.database_manager.services.activation import get_active_database_version
from common.choices import BOQStatus
from common.exceptions import AIServiceError, BOQAIError

logger = logging.getLogger("boq_ai")

_DESCRIPTION_KEYS = ("description", "item_description", "particulars", "item")
PHASE_EXTRACTED = "extracted"
PHASE_MATCHED = "matched"


def _row_description(boq_data: dict, row_id: str) -> str:
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
            stats = {
                "rows_total": 0,
                "rows_skipped": 0,
                "products_total": 0,
                "activities_total": 0,
            }

            for row_id in _row_order(boq_payload, extraction):
                row = extraction_by_row.get(row_id)
                if not row:
                    continue
                stats["rows_total"] += 1
                if row.get("skip_matching"):
                    stats["rows_skipped"] += 1
                stats["products_total"] += len(row.get("products") or [])
                stats["activities_total"] += len(row.get("activities") or [])
                extracted_rows.append(
                    {
                        **row,
                        "product_matches": [],
                    }
                )

            analysis_payload = {
                "schema_version": 2,
                "phase": PHASE_EXTRACTED,
                "boq_id": boq.pk,
                "boq_name": boq.boq_name,
                "stats": stats,
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
            stats = {
                "rows_total": 0,
                "rows_skipped": 0,
                "products_total": 0,
                "products_matched": 0,
                "products_pending": 0,
                "activities_total": 0,
            }

            for row_id in _row_order(boq_payload, existing):
                row = extraction_by_row.get(row_id)
                if not row:
                    continue
                stats["rows_total"] += 1
                stats["activities_total"] += len(row.get("activities") or [])
                skip_matching = bool(row.get("skip_matching"))
                if skip_matching:
                    stats["rows_skipped"] += 1
                    analyzed_rows.append({**row, "product_matches": []})
                    continue

                description = _row_description(boq_data, row_id)
                row_make_list = row.get("make_list") or {}
                selected_make = row_make_list.get("selected_make")
                approved_makes = make_list_service.approved_makes_for_description(description)
                if selected_make:
                    approved_makes = [selected_make]
                product_matches: list[dict[str, Any]] = []

                for product in row.get("products") or []:
                    stats["products_total"] += 1
                    product_for_match = dict(product)
                    if selected_make and not product_for_match.get("make_hint"):
                        product_for_match["make_hint"] = selected_make
                    match_result = matcher.match_product(
                        product_for_match,
                        approved_makes=approved_makes,
                    )
                    if match_result.get("status") == "matched":
                        stats["products_matched"] += 1
                    else:
                        stats["products_pending"] += 1
                    product_matches.append(
                        {
                            "product_index": product.get("product_index", 0),
                            "extracted": product,
                            "match": match_result,
                        }
                    )

                analyzed_rows.append({**row, "product_matches": product_matches})

            enricher = BOQAnalysisEnrichmentService(active_version.pk)
            analyzed_rows = enricher.enrich_rows(analyzed_rows)

            analysis_payload = {
                "schema_version": 2,
                "phase": PHASE_MATCHED,
                "boq_id": boq.pk,
                "boq_name": boq.boq_name,
                "database_version_id": active_version.pk,
                "stats": stats,
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
