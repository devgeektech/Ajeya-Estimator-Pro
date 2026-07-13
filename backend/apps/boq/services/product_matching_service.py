"""Structured + vector product matching against active Rate_Master."""
from __future__ import annotations

import logging
import re
from typing import Any

from ai.embeddings.chroma_store import ChromaEmbeddingStore, rate_document
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
        return 1.0
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
        return 1.0
    if right_size is None:
        return 0.0
    if abs(left_size - right_size) <= 0.01:
        return 1.0
    if abs(left_size - right_size) <= 1.0:
        return 0.6
    return 0.0


def structured_match_score(extracted: dict[str, Any], rate: Rate_Master) -> tuple[float, dict[str, Any]]:
    """Return 0-100 structured score and per-field breakdown."""
    extracted_attrs = {
        str(key): str(value)
        for key, value in (extracted.get("attributes") or {}).items()
    }
    rate_attrs = parse_attributes(rate.Attribute)

    breakdown: dict[str, Any] = {
        "category": _text_match_score(extracted.get("category"), rate.Category) * _TEXT_WEIGHTS["category"],
        "sub_category": _text_match_score(extracted.get("sub_category"), rate.Sub_Category)
        * _TEXT_WEIGHTS["sub_category"],
        "class": _text_match_score(extracted.get("class"), rate.Class) * _TEXT_WEIGHTS["class"],
        "size": _size_match_score(extracted.get("size"), rate.Size) * _TEXT_WEIGHTS["size"],
        "unit": _text_match_score(extracted.get("unit"), rate.Unit) * _TEXT_WEIGHTS["unit"],
        "capacity": _text_match_score(extracted.get("capacity"), rate.Capacity)
        * _TEXT_WEIGHTS["capacity"],
    }
    attr_ratio, attr_scores = attribute_overlap_score(extracted_attrs, rate_attrs)
    breakdown["attributes"] = attr_ratio * _TEXT_WEIGHTS["attributes"]
    total = sum(breakdown.values())
    breakdown["attribute_details"] = attr_scores
    return total, breakdown


def build_match_query_text(extracted: dict[str, Any]) -> str:
    parts = [
        extracted.get("description_hint"),
        extracted.get("category"),
        extracted.get("sub_category"),
        extracted.get("class"),
        extracted.get("size"),
        extracted.get("unit"),
        extracted.get("capacity"),
        extracted.get("make_hint"),
    ]
    attrs = extracted.get("attributes") or {}
    for key, value in attrs.items():
        parts.append(f"{key}={value}")
    return " ".join(str(part) for part in parts if part not in (None, ""))


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

        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        best = candidates[0] if candidates else None
        confidence = best["confidence"] if best else 0.0

        result: dict[str, Any] = {
            "status": "pending" if confidence < MATCH_CONFIDENCE_THRESHOLD else "matched",
            "confidence": confidence,
            "threshold": MATCH_CONFIDENCE_THRESHOLD,
            "approved_makes_applied": bool(approved_makes),
            "candidates": [
                {
                    "rate_master_id": item["rate_master_id"],
                    "tech_key": item["tech_key"],
                    "make": item["make"],
                    "supplier": item["supplier"],
                    "confidence": item["confidence"],
                    "chroma_similarity": item["chroma_similarity"],
                    "structured_score": item["structured_score"],
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
        category = extracted.get("category")
        if category:
            queryset = queryset.filter(Category__iexact=str(category).strip())
        sub_category = extracted.get("sub_category")
        if sub_category:
            queryset = queryset.filter(Sub_Category__iexact=str(sub_category).strip())

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
                    "rate": rate,
                }
            )
        return candidates


def rate_document_placeholder(extracted: dict[str, Any]) -> str:
    return build_match_query_text(extracted) or "product"
