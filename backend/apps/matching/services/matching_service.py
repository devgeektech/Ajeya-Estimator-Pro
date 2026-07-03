"""Product matching orchestration (Phase 5, Sprint 10).

ProductMatchingService applies the documented search strategy in priority order
(docs/DATABASE_ARCHITECTURE.md - Search Strategy):

    1. Exact match
    2. Alias match
    3. Vector (embedding) match

It persists a ProductMatch per BOQ item with a confidence score and match
reason. Items scoring below the pending threshold (< 30%) leave the product
blank and are queued for Super Admin approval
(docs/AGENTS.md - Pending Product Rules).

Confidence *scoring refinement* and explanations land in Sprint 11; here we
assign deterministic scores per strategy so downstream stages have data to work
with.
"""
from __future__ import annotations

import logging

from common.constants import CONFIDENCE_PENDING_THRESHOLD
from common.exceptions import AIServiceError
from utils.text import normalize

from ai.service import AIService
from apps.matching.services import alias_match, embedding_match, exact_match

logger = logging.getLogger("boq_ai")

# Deterministic base confidence per strategy (refined in Sprint 11).
EXACT_CONFIDENCE = 100.0
ALIAS_CONFIDENCE = 90.0


class ProductMatchingService:
    """Match BOQ items to master products for a run."""

    def __init__(self):
        self._ai_enabled = AIService.is_enabled()

    @staticmethod
    def _query_text(item) -> str:
        """Build the search text from AI extraction, falling back to the row."""
        extraction = item.ai_extraction or {}
        parts = [extraction.get(field) for field in ("product", "size", "material", "make")]
        text = " ".join(str(p) for p in parts if p)
        return text or item.description

    def _match_one(self, query: str, rates, rates_by_code: dict):
        """Return (rate_or_None, confidence, reason) for a query."""
        rate = exact_match.find_exact(query, rates)
        if rate is not None:
            return rate, EXACT_CONFIDENCE, "exact"

        rate = alias_match.find_alias(query, rates_by_code)
        if rate is not None:
            return rate, ALIAS_CONFIDENCE, "alias"

        if self._ai_enabled:
            try:
                rate, similarity = embedding_match.find_embedding(query, rates_by_code)
                if rate is not None:
                    return rate, similarity, "vector"
            except AIServiceError:
                logger.warning("Vector match skipped (AI error)")

        return None, 0.0, "no_match"

    def match_item(self, item, rates=None, rates_by_code=None, created_by=None):
        """Match a single item and persist a ProductMatch (+ pending if low)."""
        from apps.matching.models import ProductMatch
        from apps.pending_products.models import PendingProduct
        from common.choices import PendingProductStatus

        if rates is None or rates_by_code is None:
            rates, rates_by_code = self._load_rates()

        query = self._query_text(item)
        rate, confidence, reason = self._match_one(query, rates, rates_by_code)

        # Idempotent reprocessing: clear prior results for this item.
        item.product_matches.all().delete()
        PendingProduct.objects.filter(
            boq_item=item, status=PendingProductStatus.PENDING
        ).delete()

        extraction = item.ai_extraction or {}
        below_threshold = confidence < CONFIDENCE_PENDING_THRESHOLD

        # Below threshold -> leave the product blank and queue it for approval.
        match = ProductMatch.objects.create(
            boq_item=item,
            product=None if below_threshold else rate,
            confidence_score=confidence,
            make=(extraction.get("make") or (rate.make if rate else "")) or "",
            vendor=(rate.vendor if (rate and not below_threshold) else ""),
            match_reason=reason,
        )

        if below_threshold:
            PendingProduct.objects.create(
                description=item.description,
                suggested_product=(rate.product_code if rate else extraction.get("product") or ""),
                confidence_score=confidence,
                boq_item=item,
                created_by=created_by,
            )
        return match

    def match_run(self, run, created_by=None) -> int:
        """Match every item in a run. Returns the number of items processed."""
        rates, rates_by_code = self._load_rates()
        processed = 0
        for item in run.items.all():
            self.match_item(item, rates=rates, rates_by_code=rates_by_code, created_by=created_by)
            processed += 1
        logger.info("Run %s: matched %s items", run.pk, processed)
        return processed

    @staticmethod
    def _load_rates():
        """Load active-version rates as a list + normalized-code index."""
        from apps.database_manager.models import DatabaseVersion, RateMaster

        version = DatabaseVersion.objects.filter(is_active=True).first()
        if version is None:
            logger.warning("No active database version; matching has no candidates")
            return [], {}
        rates = list(RateMaster.objects.filter(database_version=version))
        rates_by_code = {normalize(rate.product_code): rate for rate in rates}
        return rates, rates_by_code
