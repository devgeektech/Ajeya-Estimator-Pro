"""Structured + vector product matching against active Rate_Master."""
from __future__ import annotations

import logging
import re
from typing import Any

from ai.embeddings.chroma_store import ChromaEmbeddingStore, rate_document, selection_amount
from ai.embeddings.generator import generate_embedding
from apps.database_manager.models import Rate_Master
from common.constants import MATCH_CONFIDENCE_THRESHOLD
from common.exceptions import AIServiceError

from .make_list_constraint_service import MakeListConstraintService
from utils.attribute_parser import attribute_overlap_score, parse_attributes

logger = logging.getLogger("boq_ai")

_TEXT_WEIGHTS = {
    "category": 25.0,
    "sub_category": 20.0,
    "class": 10.0,
    "size": 15.0,
    "unit": 5.0,
    "capacity": 5.0,
    "attributes": 20.0,
}
_CHROMA_WEIGHT = 0.35
_STRUCTURED_WEIGHT = 0.65


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _size_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"(\d+(?:\.\d+)?)", str(value))
        return float(match.group(1)) if match else None


def _text_match_score(left: Any, right: Any) -> float:
    left_text = _normalize_text(left)
    right_text = _normalize_text(right)
    if not left_text:
        return 0.0
    if not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    if left_text in right_text or right_text in left_text:
        return 0.75
    return 0.0


def _size_match_score(left: Any, right: Any) -> float:
    left_size = _size_value(left)
    right_size = _size_value(right)
    if left_size is None:
        return 0.0
    if right_size is None:
        return 0.0
    if abs(left_size - right_size) <= 0.01:
        return 1.0
    if abs(left_size - right_size) <= 1.0:
        return 0.6
    return 0.0


def structured_match_score(extracted: dict[str, Any], rate: Rate_Master) -> tuple[float, dict[str, Any]]:
    """Return 0-100 structured score using product fields only (never make/vendor)."""
    extracted_attrs = {
        str(key): str(value)
        for key, value in (extracted.get("attributes") or {}).items()
        if _is_filled(value)
        and _normalize_text(key) not in {"make", "manufacturer", "brand", "supplier", "vendor"}
    }
    rate_attrs = {
        key: value
        for key, value in parse_attributes(rate.Attribute).items()
        if _normalize_text(key) not in {"make", "manufacturer", "brand", "supplier", "vendor"}
    }

    field_checks: list[tuple[str, Any, Any, Any]] = [
        ("category", extracted.get("category"), rate.Category, _text_match_score),
        ("sub_category", extracted.get("sub_category"), rate.Sub_Category, _text_match_score),
        ("class", extracted.get("class"), rate.Class, _text_match_score),
        ("size", extracted.get("size"), rate.Size, _size_match_score),
        ("unit", extracted.get("unit"), rate.Unit, _text_match_score),
        ("capacity", extracted.get("capacity"), rate.Capacity, _text_match_score),
    ]

    breakdown: dict[str, Any] = {}
    weighted_score = 0.0
    weight_total = 0.0

    for name, left, right, scorer in field_checks:
        if not _is_filled(left):
            continue
        weight = _TEXT_WEIGHTS[name]
        points = scorer(left, right) * weight
        breakdown[name] = points
        weighted_score += points
        weight_total += weight

    if extracted_attrs:
        attr_ratio, attr_scores = attribute_overlap_score(extracted_attrs, rate_attrs)
        weight = _TEXT_WEIGHTS["attributes"]
        breakdown["attributes"] = attr_ratio * weight
        breakdown["attribute_details"] = attr_scores
        weighted_score += attr_ratio * weight
        weight_total += weight

    if weight_total <= 0:
        return 0.0, breakdown

    # Renormalize so products with fewer filled properties stay on a 0-100 scale.
    total = (weighted_score / weight_total) * 100.0
    return total, breakdown


def build_match_query_text(extracted: dict[str, Any]) -> str:
    """Build Chroma query text from filled product properties only (no make/vendor)."""
    parts = [
        extracted.get("description_hint"),
        extracted.get("category"),
        extracted.get("sub_category"),
        extracted.get("class"),
        extracted.get("size"),
        extracted.get("unit"),
        extracted.get("capacity"),
        # Intentionally omit make_hint / supplier — product identity only.
    ]
    attrs = extracted.get("attributes") or {}
    for key, value in attrs.items():
        if not _is_filled(value):
            continue
        # Skip make/vendor-like attribute keys so they do not bias product score.
        key_norm = _normalize_text(key)
        if key_norm in {"make", "manufacturer", "brand", "supplier", "vendor"}:
            continue
        parts.append(f"{key}={value}")
    return " ".join(str(part).strip() for part in parts if _is_filled(part))


class ProductMatchingService:
    """Match extracted products to Rate_Master using Chroma recall + structured scoring."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id
        self._store = ChromaEmbeddingStore()

    def match_product(
        self,
        extracted: dict[str, Any],
        *,
        approved_makes: list[str] | None = None,
        prefer_lowest_price: bool = False,
        chroma_limit: int = 25,
    ) -> dict[str, Any]:
        query_text = build_match_query_text(extracted)
        candidates: list[dict[str, Any]] = []

        try:
            embedding = generate_embedding(query_text or rate_document_placeholder(extracted))
            hits = self._store.query_similar(
                embedding,
                limit=chroma_limit,
                database_version_id=self.database_version_id,
            )
        except AIServiceError:
            logger.warning("Chroma query skipped; falling back to structured SQL filter")
            hits = []

        rate_map = self._load_rates([hit["rate_master_id"] for hit in hits])
        for hit in hits:
            rate = rate_map.get(hit["rate_master_id"])
            if rate is None:
                continue
            structured, breakdown = structured_match_score(extracted, rate)
            chroma_score = float(hit.get("similarity", 0.0)) * 100.0
            confidence = (_CHROMA_WEIGHT * chroma_score) + (_STRUCTURED_WEIGHT * structured)
            candidates.append(
                {
                    "rate_master_id": rate.pk,
                    "tech_key": rate.Tech_Key,
                    "make": rate.Make,
                    "supplier": rate.Supplier,
                    "confidence": round(confidence, 2),
                    "chroma_similarity": round(chroma_score, 2),
                    "structured_score": round(structured, 2),
                    "score_breakdown": breakdown,
                    "selection_amount": float(selection_amount(rate)),
                    "rate": rate,
                }
            )

        if not candidates:
            candidates = self._sql_fallback_candidates(extracted)

        if approved_makes:
            filtered = [
                candidate
                for candidate in candidates
                if MakeListConstraintService.make_is_allowed(candidate.get("make"), approved_makes)
            ]
            candidates = filtered

        if prefer_lowest_price and candidates:
            # Prefer cheapest approved-make candidate; confidence is tie-breaker.
            candidates.sort(
                key=lambda item: (
                    float(item.get("selection_amount") or 0.0),
                    -float(item.get("confidence") or 0.0),
                )
            )
        else:
            candidates.sort(key=lambda item: item["confidence"], reverse=True)

        best = candidates[0] if candidates else None
        confidence = best["confidence"] if best else 0.0

        result: dict[str, Any] = {
            "status": "pending" if confidence < MATCH_CONFIDENCE_THRESHOLD else "matched",
            "confidence": confidence,
            "threshold": MATCH_CONFIDENCE_THRESHOLD,
            "approved_makes_applied": bool(approved_makes),
            "prefer_lowest_price": prefer_lowest_price,
            "candidates": [
                {
                    "rate_master_id": item["rate_master_id"],
                    "tech_key": item["tech_key"],
                    "make": item["make"],
                    "supplier": item["supplier"],
                    "confidence": item["confidence"],
                    "chroma_similarity": item["chroma_similarity"],
                    "structured_score": item["structured_score"],
                    "selection_amount": item.get("selection_amount"),
                }
                for item in candidates[:5]
            ],
        }
        if best and confidence >= MATCH_CONFIDENCE_THRESHOLD:
            result["selected"] = {
                "rate_master_id": best["rate_master_id"],
                "tech_key": best["tech_key"],
                "make": best["make"],
                "supplier": best["supplier"],
                "selection_amount": best.get("selection_amount"),
            }
        return result

    def _load_rates(self, rate_ids: list[int]) -> dict[int, Rate_Master]:
        if not rate_ids:
            return {}
        rows = Rate_Master.objects.filter(
            pk__in=rate_ids,
            database_version_id=self.database_version_id,
        )
        return {row.pk: row for row in rows}

    def _sql_fallback_candidates(self, extracted: dict[str, Any]) -> list[dict[str, Any]]:
        queryset = Rate_Master.objects.filter(database_version_id=self.database_version_id)
        # Apply filters only for filled properties — never constrain on null/blank.
        category = extracted.get("category")
        if _is_filled(category):
            queryset = queryset.filter(Category__iexact=str(category).strip())
        sub_category = extracted.get("sub_category")
        if _is_filled(sub_category):
            queryset = queryset.filter(Sub_Category__iexact=str(sub_category).strip())
        product_class = extracted.get("class")
        if _is_filled(product_class):
            queryset = queryset.filter(Class__iexact=str(product_class).strip())
        size = extracted.get("size")
        if _is_filled(size):
            queryset = queryset.filter(Size__icontains=str(size).strip())

        candidates: list[dict[str, Any]] = []
        for rate in queryset[:50]:
            structured, breakdown = structured_match_score(extracted, rate)
            candidates.append(
                {
                    "rate_master_id": rate.pk,
                    "tech_key": rate.Tech_Key,
                    "make": rate.Make,
                    "supplier": rate.Supplier,
                    "confidence": round(structured, 2),
                    "chroma_similarity": 0.0,
                    "structured_score": round(structured, 2),
                    "score_breakdown": breakdown,
                    "selection_amount": float(selection_amount(rate)),
                    "rate": rate,
                }
            )
        return candidates


def rate_document_placeholder(extracted: dict[str, Any]) -> str:
    return build_match_query_text(extracted) or "product"
