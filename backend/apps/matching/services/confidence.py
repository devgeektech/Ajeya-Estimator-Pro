"""Confidence scoring + explanations (Phase 5, Sprint 11).

Refines the base score produced by matching into a factor-weighted confidence
(docs/TRD.md - Confidence Calculation): extracted product specification
agreement between the BOQ item and the matched master product.
Stores a colour band (docs/TRD.md - Confidence Thresholds via
common.constants.confidence_band) and a human-readable explanation.

When AI is enabled the OpenAI validation prompt enriches the explanation and
blends its confidence; AI is used only for validation, never pricing/supplier selection
(docs/AGENTS.md - AI Rules). With AI disabled, scoring is fully deterministic.
"""
from __future__ import annotations

import logging

from common.constants import confidence_band
from common.exceptions import AIServiceError
from utils.text import normalize

from ai.service import AIService
from apps.matching.models import ProductMatch

logger = logging.getLogger("boq_ai")

# Factor weights (sum to 100) used when the item has AI extraction to compare.
FACTOR_WEIGHTS = {
    "category": 15,
    "sub_category": 15,
    "class": 15,
    "size_mm": 20,
    "make": 15,
    "capacity": 5,
    "unit": 5,
    "supplier": 10,
}

# Authoritative base score per match strategy.
BASE_SCORES = {"exact": 100.0, "alias": 90.0, "no_match": 0.0}


class ConfidenceService:
    """Score ProductMatch rows and attach explanations."""

    def __init__(self):
        self._ai_enabled = AIService.is_enabled()

    @staticmethod
    def _factor_agreement(extraction: dict, match) -> tuple[float | None, list[str], list[str]]:
        """Return (factor_percent, matched_factors, missing_factors).

        factor_percent is None when the extraction provides no comparable fields.
        """
        product = match.product
        comparable = ConfidenceService._product_extraction_for_match(extraction, match)
        haystack = normalize(
            " ".join(
                str(value)
                for value in (
                    product.tech_key,
                    product.category,
                    product.sub_category,
                    product.unit,
                    product.make,
                    product.supplier,
                    product.product_class,
                    product.size_mm,
                    product.capacity,
                    product.height,
                    product.working_pressure,
                    product.test_pressure,
                    product.temperature,
                    product.throw_distance,
                    product.k_factor,
                    product.head,
                )
                if value
            )
        )
        considered_weight = 0
        earned_weight = 0
        matched: list[str] = []
        missing: list[str] = []

        for field, weight in FACTOR_WEIGHTS.items():
            value = normalize(comparable.get(field))
            if not value:
                continue
            considered_weight += weight
            target = normalize(product.make) if field == "make" else haystack
            if value in target:
                earned_weight += weight
                matched.append(field)
            else:
                missing.append(field)

        if considered_weight == 0:
            return None, matched, missing
        return round(earned_weight / considered_weight * 100, 2), matched, missing

    @staticmethod
    def _product_extraction_for_match(extraction: dict, match) -> dict:
        products = extraction.get("products") if isinstance(extraction, dict) else None
        if isinstance(products, list):
            index = getattr(match, "extraction_index", 0) or 0
            if 0 <= index < len(products) and isinstance(products[index], dict):
                return products[index]
            for product in products:
                if isinstance(product, dict):
                    return product
        return extraction if isinstance(extraction, dict) else {}

    def _ai_validation(self, description: str, product):
        """Return (confidence_or_None, reason_or_None) from OpenAI validation."""
        if not self._ai_enabled or product is None:
            return None, None
        try:
            result = AIService().run_json_prompt(
                "validation.txt",
                description=description,
                candidate=self._product_candidate_text(product),
            )
        except AIServiceError:
            logger.warning("AI validation skipped (AI error)")
            return None, None
        confidence = result.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        return confidence, result.get("reason")

    @staticmethod
    def _product_candidate_text(product) -> str:
        return " ".join(
            str(value)
            for value in (
                product.tech_key,
                product.category,
                product.sub_category,
                product.product_class,
                product.size_mm,
                product.make,
                product.capacity,
                product.unit,
                product.supplier,
            )
            if value
        )

    def evaluate(self, match) -> float:
        """Recompute confidence + explanation for a single ProductMatch."""
        reason = match.match_reason
        product = match.product
        item = match.boq_item
        extraction = item.ai_extraction or {}

        if product is None or reason == "no_match":
            match.confidence_score = 0.0
            match.ai_explanation = "No matching product found."
            match.save(update_fields=["confidence_score", "ai_explanation"])
            return 0.0

        base = BASE_SCORES.get(reason, float(match.confidence_score))
        factor_pct, matched, missing = self._factor_agreement(extraction, match)

        # Exact matches are authoritative; otherwise blend base with factor
        # agreement when extraction data is available.
        if reason == "exact" or factor_pct is None:
            score = base
        else:
            score = round((base + factor_pct) / 2, 2)

        ai_confidence, ai_reason = self._ai_validation(item.description, product)
        if ai_confidence is not None:
            score = round((score + ai_confidence) / 2, 2)

        score = max(0.0, min(100.0, score))

        explanation = self._build_explanation(reason, matched, missing, ai_reason)
        match.confidence_score = score
        match.ai_explanation = explanation
        match.save(update_fields=["confidence_score", "ai_explanation"])
        return score

    @staticmethod
    def _build_explanation(reason, matched, missing, ai_reason) -> str:
        parts = [f"{reason} match"]
        if matched:
            parts.append(f"agrees on {', '.join(matched)}")
        if missing:
            parts.append(f"differs on {', '.join(missing)}")
        text = "; ".join(parts)
        if ai_reason:
            text = f"{text} | AI: {ai_reason}"
        return text[:1000]

    def score_run(self, run) -> int:
        """Score every match in a run. Returns the number of matches scored."""
        matches = ProductMatch.objects.filter(
            boq_item__boq_run=run
        ).select_related("boq_item", "product")
        count = 0
        for match in matches:
            self.evaluate(match)
            count += 1
        logger.info("Run %s: scored %s matches", run.pk, count)
        return count


def band_for(score) -> str:
    """Colour band label for a score (thin wrapper over common.constants)."""
    return confidence_band(float(score) if score is not None else None)
