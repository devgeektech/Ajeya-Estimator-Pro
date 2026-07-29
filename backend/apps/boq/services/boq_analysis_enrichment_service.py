"""Enrich analysis rows with rate, labour, and priced line output."""
from __future__ import annotations

from typing import Any

from common.constants import MATCH_CONFIDENCE_THRESHOLD

from .boq_line_output_service import BOQLineOutputService
from .labour_detail_retrieval_service import LabourDetailRetrievalService
from .rate_detail_retrieval_service import RateDetailRetrievalService


class BOQAnalysisEnrichmentService:
    """Attach Rate_Master / Labour_Master snapshots after product matching."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id
        self._rates = RateDetailRetrievalService(database_version_id)
        self._labour = LabourDetailRetrievalService(database_version_id)

    def enrich_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for row in rows:
            product_matches = []
            for item in row.get("product_matches") or []:
                product_matches.append(self._enrich_product_match(item))
            enriched.append({**row, "product_matches": product_matches})
        return enriched

    def _enrich_product_match(self, item: dict[str, Any]) -> dict[str, Any]:
        match = item.get("match") or {}
        extracted = item.get("extracted") or {}
        confidence = float(match.get("confidence") or 0)
        is_pending = match.get("status") != "matched" or confidence < MATCH_CONFIDENCE_THRESHOLD

        rate_detail = None
        labour_detail = None
        selected = match.get("selected")
        if not is_pending and selected:
            rate_detail = self._rates.get_by_id(int(selected["rate_master_id"]))
            if rate_detail:
                labour_detail = self._labour.get_by_tech_key(
                    rate_detail.get("tech_key"),
                    size=rate_detail.get("size"),
                )

        line_output = BOQLineOutputService.build(
            quantity=extracted.get("quantity"),
            rate_detail=rate_detail,
            labour_detail=labour_detail,
            is_pending=is_pending,
            rate_only=bool(extracted.get("rate_only")),
        )

        return {
            **item,
            "rate_detail": rate_detail,
            "labour_detail": labour_detail,
            "line_output": line_output,
        }
