"""Product matching orchestration (Phase 5, Sprint 10).

ProductMatchingService applies the documented search strategy in priority order
(docs/DATABASE_ARCHITECTURE.md - Search Strategy):

    1. Exact match
    2. Vector (embedding) match

It persists a ProductMatch per BOQ item with a confidence score and match
reason. Items scoring below the confidence threshold (< 30%) leave the product
blank for expert review.

Confidence scoring is refined after matching; this service assigns the
deterministic strategy score used by downstream stages.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from common.constants import CONFIDENCE_PENDING_THRESHOLD
from common.exceptions import AIServiceError
from utils.text import normalize

from ai.service import AIService
from apps.database_manager.models import DatabaseVersion, RateMaster
from apps.matching.models import ProductMatch
from apps.matching.services import embedding_match, exact_match

logger = logging.getLogger("boq_ai")

# Deterministic base confidence per strategy (refined in Sprint 11).
EXACT_CONFIDENCE = 100.0


class ProductMatchingService:
    """Match BOQ items to master products for a run."""

    def __init__(self):
        self._ai_enabled = AIService.is_enabled()

    @staticmethod
    def _query_texts(item) -> list[str]:
        """Build database-search queries, always preferring the source BOQ row."""
        extraction = item.ai_extraction or {}
        candidates: list[str] = [item.description]

        for product in ProductMatchingService._extracted_products(extraction):
            candidates.extend(ProductMatchingService._product_queries(product))

        queries: list[str] = []
        seen: set[str] = set()
        for query in candidates:
            text = str(query).strip()
            key = normalize(text)
            if not text or key in seen:
                continue
            seen.add(key)
            queries.append(text)
        return queries

    @staticmethod
    def _candidate_queries(item, product: dict | None) -> list[str]:
        """Build search queries for one extracted product candidate."""
        if not isinstance(product, dict):
            return ProductMatchingService._query_texts(item)

        candidates = ProductMatchingService._product_queries(product)
        if not candidates:
            candidates = [item.description]

        queries: list[str] = []
        seen: set[str] = set()
        for query in candidates:
            text = str(query).strip()
            key = normalize(text)
            if not text or key in seen:
                continue
            seen.add(key)
            queries.append(text)
        return queries

    @staticmethod
    def _product_query(product: dict) -> str:
        queries = ProductMatchingService._product_queries(product)
        return queries[0] if queries else ""

    @staticmethod
    def _product_queries(product: dict) -> list[str]:
        parts = [
            product.get(field)
            for field in (
                "product_name",
                "product",
                "size",
                "material",
                "make",
                "category",
                "sub_category",
                "class",
                "size_mm",
                "capacity",
                "unit",
                "height",
                "working_pressure",
                "test_pressure",
                "temperature",
                "throw",
                "k_factor",
                "head",
                "supplier",
            )
        ]
        queries = [" ".join(str(part) for part in parts if part).strip()]
        size = product.get("size_mm") or product.get("size")
        sub_category = product.get("sub_category")
        product_class = product.get("class")
        category = product.get("category")
        for variant in (
            (size, sub_category),
            (sub_category, size),
            (size, product_class, sub_category),
            (category, sub_category),
        ):
            text = " ".join(str(part) for part in variant if part).strip()
            if text:
                queries.append(text)
        return [query for query in queries if query]

    @staticmethod
    def _candidate_label(item, product: dict | None) -> str:
        if not isinstance(product, dict):
            return item.description
        for field in (
            "product_name",
            "sub_category",
            "category",
            "class",
            "size_mm",
            "capacity",
            "make",
        ):
            value = product.get(field)
            if value:
                return str(value).strip()
        query = ProductMatchingService._product_query(product)
        return query or item.description

    @staticmethod
    def _rate_payload(rate) -> dict:
        return {
            "id": rate.pk,
            "tech_key": rate.tech_key,
            "category": rate.category,
            "sub_category": rate.sub_category,
            "class": rate.product_class,
            "size_mm": str(rate.size_mm) if rate.size_mm is not None else None,
            "make": rate.make,
            "capacity": rate.capacity,
            "unit": rate.unit,
            "supplier": rate.supplier,
        }

    @staticmethod
    def _split_extracted_products(item, matches) -> None:
        extraction = item.ai_extraction if isinstance(item.ai_extraction, dict) else {}
        candidates = ProductMatchingService._extracted_products(extraction)
        database_products: list[dict] = []
        missing_products: list[dict] = []
        for match in matches:
            index = int(match.extraction_index or 0)
            product = candidates[index] if 0 <= index < len(candidates) else None
            if match.product_id:
                database_products.append({
                    **(product or {}),
                    "extraction_index": index,
                    "matched_product": ProductMatchingService._rate_payload(match.product),
                    "match_type": match.match_type or match.match_reason,
                    "confidence_score": float(match.confidence_score or 0),
                    "review_required": match.review_required,
                })
            else:
                missing_products.append({
                    **(product or {
                        "product_name": ProductMatchingService._candidate_label(item, product)
                    }),
                    "extraction_index": index,
                    "match_type": "no_match",
                    "confidence_score": float(match.confidence_score or 0),
                    "review_required": True,
                })

        item.ai_extraction = {
            **extraction,
            "database_products": database_products,
            "missing_products": missing_products,
            "activities": extraction.get("activities", []),
        }
        item.save(update_fields=["ai_extraction"])

    def _match_one(self, query: str, rates, rates_by_code: dict):
        """Return (rate_or_None, confidence, reason) for a query."""
        rate = exact_match.find_exact(query, rates)
        if rate is not None:
            return rate, EXACT_CONFIDENCE, "exact"

        if self._ai_enabled:
            try:
                rate, similarity = embedding_match.find_embedding(query, rates_by_code)
                if rate is not None:
                    return rate, similarity, "vector"
            except AIServiceError:
                logger.warning("Vector match skipped (AI error)")

        return None, 0.0, "no_match"

    @staticmethod
    def _product_candidates(item) -> list[dict | None]:
        extraction = item.ai_extraction or {}
        products = ProductMatchingService._extracted_products(extraction)
        if products:
            return products
        return [None]

    @staticmethod
    def _extracted_products(extraction: dict) -> list[dict]:
        if not isinstance(extraction, dict):
            return []
        products: list[dict] = []
        for key in ("database_products", "missing_products"):
            values = extraction.get(key)
            if isinstance(values, list):
                products.extend(product for product in values if isinstance(product, dict))
        legacy = extraction.get("products")
        if not products and isinstance(legacy, list):
            products.extend(product for product in legacy if isinstance(product, dict))
        return products

    @staticmethod
    def _decimal(value, default: str = "1") -> Decimal:
        if value in (None, ""):
            return Decimal(default)
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal(default)

    def _match_candidate(
        self,
        item,
        product: dict | None,
        extraction_index: int,
        rates,
        rates_by_code: dict,
    ):
        rate = None
        confidence = 0.0
        reason = "no_match"
        for query in self._candidate_queries(item, product):
            rate, confidence, reason = self._match_one(query, rates, rates_by_code)
            if rate is not None:
                break

        below_threshold = confidence < CONFIDENCE_PENDING_THRESHOLD
        quantity_basis = str((product or {}).get("quantity_basis") or "unknown").strip()
        if quantity_basis not in {"per_boq_unit", "total_for_boq_row", "unknown"}:
            quantity_basis = "unknown"
        review_required = below_threshold or quantity_basis == "unknown"
        match = ProductMatch.objects.create(
            boq_item=item,
            product=None if below_threshold else rate,
            confidence_score=confidence,
            make=(rate.make if (rate and not below_threshold) else "") or "",
            supplier=(rate.supplier if (rate and not below_threshold) else ""),
            match_reason=reason,
            match_type=reason,
            extraction_index=extraction_index,
            product_quantity=self._decimal((product or {}).get("product_quantity")),
            product_unit=str((product or {}).get("product_unit") or (product or {}).get("unit") or ""),
            quantity_basis=quantity_basis,
            quantity_source=str((product or {}).get("quantity_source") or ""),
            review_required=review_required,
        )
        return match

    def match_item(self, item, rates=None, rates_by_code=None):
        """Match all extracted products for one BOQ item."""
        if rates is None or rates_by_code is None:
            rates, rates_by_code = self._load_rates()

        # Idempotent reprocessing: clear prior results for this item.
        item.product_matches.all().delete()

        matches = [
            self._match_candidate(
                item,
                product,
                index,
                rates,
                rates_by_code,
            )
            for index, product in enumerate(self._product_candidates(item))
        ]
        self._split_extracted_products(item, matches)
        return matches[0] if matches else None

    def match_run(self, run) -> int:
        """Match every item in a run. Returns the number of items processed."""
        rates, rates_by_code = self._load_rates()
        processed = 0
        for item in run.items.all():
            self.match_item(item, rates=rates, rates_by_code=rates_by_code)
            processed += 1
        logger.info("Run %s: matched %s items", run.pk, processed)
        return processed

    @staticmethod
    def _load_rates():
        """Load active-version rates as a list + normalized-code index."""
        version = DatabaseVersion.objects.filter(is_active=True).first()
        if version is None:
            logger.warning("No active database version; matching has no candidates")
            return [], {}
        rates = list(RateMaster.objects.filter(database_version=version))
        rates_by_code: dict[str, list[RateMaster]] = {}
        for rate in rates:
            key = normalize(rate.tech_key)
            if key:
                rates_by_code.setdefault(key, []).append(rate)
        return rates, rates_by_code
