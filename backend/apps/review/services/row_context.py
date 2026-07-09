"""Build review-page context for BOQ items (products and activities)."""
from __future__ import annotations

from apps.matching.services.confidence import band_for
from apps.review.services.review_service import ReviewService


def _product_label(product: dict) -> str:
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
    return "Unnamed product"


def _match_entry(match) -> dict:
    detail = getattr(match, "rate_detail", None)
    return {
        "match": match,
        "rate_detail": detail,
        "band": band_for(match.confidence_score) if match else "blank",
        "label": match.product.tech_key if match.product_id else "No match",
    }


def build_review_row_context(item, service: ReviewService) -> dict:
    """Return review context with matched/unmatched products and activities."""
    extraction = item.ai_extraction if isinstance(item.ai_extraction, dict) else {}
    matches = list(
        item.product_matches.select_related("product", "rate_detail")
        .order_by("extraction_index", "pk")
    )
    primary_match = matches[0] if matches else None
    primary_detail = getattr(primary_match, "rate_detail", None) if primary_match else None

    database_products = [
        product
        for product in extraction.get("database_products", [])
        if isinstance(product, dict)
    ]
    missing_products = [
        product
        for product in extraction.get("missing_products", [])
        if isinstance(product, dict)
    ]
    database_activities = list(
        extraction.get("database_activities") or extraction.get("activities") or []
    )
    missing_activities = list(extraction.get("missing_activities") or [])

    return {
        "item": item,
        "match": primary_match,
        "matches": [_match_entry(match) for match in matches],
        "breakdown": primary_detail,
        "rate_detail": primary_detail,
        "band": band_for(primary_match.confidence_score) if primary_match else "blank",
        "candidates": service.candidate_rates(item),
        "database_products": database_products,
        "missing_products": missing_products,
        "database_activities": database_activities,
        "missing_activities": missing_activities,
        "product_label": _product_label,
    }


def build_review_summary(rows: list[dict]) -> dict:
    """Aggregate matched/missing counts for the review page header."""
    matched_products = 0
    missing_products = 0
    database_activities = 0
    missing_activities = 0
    for row in rows:
        matched_products += len(row.get("database_products", []))
        missing_products += len(row.get("missing_products", []))
        database_activities += len(row.get("database_activities", []))
        missing_activities += len(row.get("missing_activities", []))
    return {
        "matched_products": matched_products,
        "missing_products": missing_products,
        "database_activities": database_activities,
        "missing_activities": missing_activities,
    }
