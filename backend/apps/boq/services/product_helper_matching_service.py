"""Match extracted BOQ products to Product_Helper catalog rows (Product_ID)."""
from __future__ import annotations

import logging
import re
from typing import Any

from apps.database_manager.models import Product_Helper
from common.constants import MATCH_CONFIDENCE_THRESHOLD
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
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    if left_text in right_text or right_text in left_text:
        return 0.75
    return 0.0


def _size_match_score(left: Any, right: Any) -> float:
    left_size = _size_value(left)
    right_size = _size_value(right)
    if left_size is None or right_size is None:
        return 0.0
    if abs(left_size - right_size) <= 0.01:
        return 1.0
    if abs(left_size - right_size) <= 1.0:
        return 0.6
    return 0.0


def structured_helper_match_score(
    extracted: dict[str, Any],
    helper: Product_Helper,
) -> tuple[float, dict[str, Any]]:
    """Return 0–100 structured score vs a Product_Helper row (no make/vendor)."""
    extracted_attrs = {
        str(key): str(value)
        for key, value in (extracted.get("attributes") or {}).items()
        if _is_filled(value)
        and _normalize_text(key)
        not in {"make", "manufacturer", "brand", "supplier", "vendor"}
    }
    helper_attrs = {
        key: value
        for key, value in parse_attributes(helper.Attribute).items()
        if _normalize_text(key)
        not in {"make", "manufacturer", "brand", "supplier", "vendor"}
    }

    field_checks: list[tuple[str, Any, Any, Any]] = [
        ("category", extracted.get("category"), helper.Category, _text_match_score),
        (
            "sub_category",
            extracted.get("sub_category"),
            helper.Sub_Category,
            _text_match_score,
        ),
        ("class", extracted.get("class"), helper.Class, _text_match_score),
        ("size", extracted.get("size"), helper.Size, _size_match_score),
        ("unit", extracted.get("unit"), helper.Unit, _text_match_score),
        ("capacity", extracted.get("capacity"), helper.Capacity, _text_match_score),
    ]

    weighted = 0.0
    weight_total = 0.0
    breakdown: dict[str, Any] = {}
    for name, left, right, scorer in field_checks:
        weight = _TEXT_WEIGHTS[name]
        if not _is_filled(left):
            continue
        weight_total += weight
        score = float(scorer(left, right))
        weighted += weight * score
        breakdown[name] = {"score": round(score, 3), "weight": weight}

    attr_weight = _TEXT_WEIGHTS["attributes"]
    if extracted_attrs:
        weight_total += attr_weight
        attr_ratio, _attr_details = attribute_overlap_score(extracted_attrs, helper_attrs)
        attr_score = float(attr_ratio)
        weighted += attr_weight * attr_score
        breakdown["attributes"] = {"score": round(attr_score, 3), "weight": attr_weight}

    if weight_total <= 0:
        return 0.0, breakdown
    return round(100.0 * weighted / weight_total, 2), breakdown


def helper_to_snapshot(helper: Product_Helper) -> dict[str, Any]:
    """JSON-safe Product_Helper snapshot for analysis / Make & Vendor."""
    size = helper.Size
    size_text = None
    if size is not None:
        size_text = format(size, "f").rstrip("0").rstrip(".")
    return {
        "product_helper_id": helper.pk,
        "product_id": helper.Product_ID,
        "category": helper.Category,
        "sub_category": helper.Sub_Category,
        "class": helper.Class,
        "size": size_text,
        "unit": helper.Unit,
        "capacity": helper.Capacity,
        "attribute": helper.Attribute,
        "status": helper.Status,
        "tech_key": helper.display_key(),
        "summary": helper.display_key(),
    }


class ProductHelperMatchingService:
    """Match BOQ extracts onto Product_Helper to obtain Product_ID."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id
        self._helpers: list[Product_Helper] | None = None

    def _load_helpers(self) -> list[Product_Helper]:
        if self._helpers is None:
            self._helpers = list(
                Product_Helper.objects.filter(
                    database_version_id=self.database_version_id
                )
            )
        return self._helpers

    def match_product(
        self,
        extracted: dict[str, Any],
        *,
        limit: int = 3,
    ) -> dict[str, Any]:
        helpers = self._load_helpers()
        if not helpers:
            return {
                "status": "unmatched",
                "confidence": 0.0,
                "threshold": MATCH_CONFIDENCE_THRESHOLD,
                "candidates": [],
                "best": None,
            }

        scored: list[dict[str, Any]] = []
        for helper in helpers:
            # Skip inactive catalog rows when Status is present.
            status = str(helper.Status or "").strip().lower()
            if status and status not in {"active", "a", "1", "yes", "y"}:
                continue
            confidence, breakdown = structured_helper_match_score(extracted, helper)
            if confidence <= 0:
                continue
            snapshot = helper_to_snapshot(helper)
            scored.append(
                {
                    **snapshot,
                    "confidence": confidence,
                    "score_breakdown": breakdown,
                    "helper": helper,
                }
            )

        scored.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
        candidates = scored[: max(1, int(limit))]
        best = candidates[0] if candidates else None
        confidence = float(best["confidence"]) if best else 0.0
        status = "matched" if confidence >= MATCH_CONFIDENCE_THRESHOLD else "pending"
        if best is None:
            status = "unmatched"
        return {
            "status": status,
            "confidence": confidence,
            "threshold": MATCH_CONFIDENCE_THRESHOLD,
            "candidates": [
                {key: value for key, value in item.items() if key != "helper"}
                for item in candidates
            ],
            "best": (
                {key: value for key, value in best.items() if key != "helper"}
                if best
                else None
            ),
            "best_helper": best.get("helper") if best else None,
        }

    def get_by_product_id(self, product_id: str | None) -> Product_Helper | None:
        text = str(product_id or "").strip()
        if not text:
            return None
        return (
            Product_Helper.objects.filter(
                database_version_id=self.database_version_id,
                Product_ID=text,
            )
            .order_by("pk")
            .first()
        )
