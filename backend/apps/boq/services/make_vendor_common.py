"""Shared Make & Vendor helpers used by rates / cascade / display mixins."""
from __future__ import annotations

import re
from typing import Any

from apps.boq.services.boq_row_fields import normalize_text as _normalize_text
from apps.boq.services.make_list_constraint_service import (
    MakeListConstraintService,
    _make_fingerprint,
    makes_optimally_match,
)
from apps.database_manager.models import Rate_Master_Output


_SUBCATEGORY_SEP = "::"


SAME_PRICE_TIE_LABEL = "Multiple product detected in same price"


def _align_option_label(value: str | None, options: list[str] | None) -> str:
    """Map a stored make/vendor onto the Rate_Master spelling used in dropdowns.

    Make-list labels (``NEWAGE``) often differ from Rate_Master (``NEW AGE``).
    Selecting the wrong spelling leaves Alpine x-model with no matching
    ``<option>``, so the UI shows ``Select make…`` while the rate is filled.
    """
    text = str(value or "").strip()
    choices = [str(item).strip() for item in (options or []) if str(item).strip()]
    if not text:
        return ""
    if text in choices:
        return text
    text_fp = _make_fingerprint(text)
    for option in choices:
        if makes_optimally_match(text, option):
            return option
        if text_fp and text_fp == _make_fingerprint(option):
            return option
    return text


def _catalog_product_id(product: dict[str, Any] | None) -> str:
    """Return Product_Helper / Rate_Master Product_ID when known on the product."""
    item = product or {}
    selection = item.get("vendor_selection") or {}
    mapping = item.get("ai_mapping") or {}
    for key in (
        "catalog_product_id",
        "product_id",
        "suggested_catalog_product_id",
    ):
        text = str(item.get(key) or selection.get(key) or mapping.get(key) or "").strip()
        if text:
            return text
    return ""


def _analysis_rate_master_pk(product: dict[str, Any] | None) -> int | None:
    """Rate_Master_Output pk chosen on Analysis (Select / match / confirm)."""
    item = product or {}
    mapping = item.get("ai_mapping") or {}
    for raw in (
        item.get("db_product_id"),
        item.get("suggested_db_product_id"),
        mapping.get("selected_rate_master_id"),
        mapping.get("selected_id"),
    ):
        if raw in (None, ""):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    for candidate in item.get("db_candidates") or []:
        if not isinstance(candidate, dict) or not candidate.get("is_selected"):
            continue
        raw = candidate.get("id") or candidate.get("rate_master_id")
        if raw in (None, ""):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_material_rate_key(value: Any) -> str:
    """Stable compare key for material rates shown on Make & Vendor."""
    text = str(value or "").strip()
    if not text or text in {"—", "-", "n/a", "N/A"}:
        return ""
    cleaned = re.sub(r"[^\d.-]", "", text.replace(",", ""))
    if not cleaned or cleaned in {".", "-", "-."}:
        return ""
    try:
        return f"{float(cleaned):.4f}"
    except (TypeError, ValueError):
        return _normalize_text(text)


def _build_same_price_choices(
    scored: list[tuple[float, Rate_Master_Output, dict[str, Any], float]],
) -> list[dict[str, Any]]:
    """
    When lowest-price pick has multiple Rate_Master_Output rows at the same amount
    for the winning make (typically different vendors), return selectable choices.
    """
    if len(scored) < 2:
        return []
    lowest_amount = float(scored[0][3])
    winner_make = _normalize_text(scored[0][1].Make)
    ties: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for confidence, rate, _breakdown, amount in scored:
        if abs(float(amount) - lowest_amount) > 0.0001:
            continue
        if winner_make and _normalize_text(rate.Make) != winner_make:
            continue
        rate_id = int(rate.pk)
        if rate_id in seen_ids:
            continue
        seen_ids.add(rate_id)
        ties.append(
            {
                "rate_master_id": rate_id,
                "make": str(rate.Make or "").strip(),
                "vendor": str(rate.Vendor or "").strip(),
                "amount": round(float(amount), 4),
                "product_id": rate.Product_ID,
                "rate_id": rate.Rate_ID,
                "tech_key": rate.display_key(),
                "confidence": round(float(confidence), 2),
                "summary": _product_summary(
                    {
                        "category": rate.Category,
                        "sub_category": rate.Sub_Category,
                        "class": rate.Class,
                        "size": rate.Size,
                        "unit": rate.Unit,
                        "capacity": rate.Capacity,
                    }
                ),
            }
        )
    # Need at least two distinct vendors (or product rows) at that price.
    if len(ties) < 2:
        return []
    vendors = {_normalize_text(item.get("vendor")) for item in ties}
    # Flag when multiple vendors share the price, or multiple products same vendor.
    if len(vendors) >= 2 or len(ties) >= 2:
        return ties
    return []


def _flag_same_material_rate_vendor_review(lines: list[dict[str, Any]]) -> int:
    """
    Highlight products that share the same material rate but use different
    make/vendor pairs — expert must confirm the vendor choice.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        for product in line.get("products") or []:
            product["vendor_rate_review"] = False
            line_output = product.get("line_output") or {}
            rate_key = _normalize_material_rate_key(line_output.get("material_rate"))
            if not rate_key:
                continue
            if str(product.get("match_status") or "") != "matched":
                continue
            buckets.setdefault(rate_key, []).append(product)

    flagged = 0
    for products in buckets.values():
        if len(products) < 2:
            continue
        combos = {
            (
                _normalize_text(item.get("selected_make")),
                _normalize_text(item.get("selected_vendor")),
            )
            for item in products
        }
        if len(combos) < 2:
            continue
        for item in products:
            item["vendor_rate_review"] = True
            flagged += 1
    return flagged


def _product_summary(product: dict[str, Any]) -> str:
    parts = [
        product.get("description_hint"),
        product.get("category"),
        product.get("sub_category"),
        product.get("class"),
    ]
    size = product.get("size")
    unit = product.get("unit")
    if size not in (None, ""):
        parts.append(f"{size}{unit or ''}")
    capacity = product.get("capacity")
    if capacity not in (None, ""):
        parts.append(str(capacity))
    return " / ".join(str(part) for part in parts if part not in (None, "")) or "Product"


def _taxonomy_label(product: dict[str, Any]) -> str:
    category = str(product.get("category") or "").strip()
    sub_category = str(product.get("sub_category") or "").strip()
    if category and sub_category:
        return f"{category} / {sub_category}"
    return category or sub_category or "—"


def _subcategory_storage_key(category: str, sub_category: str) -> str:
    return f"{str(category or '').strip()}{_SUBCATEGORY_SEP}{str(sub_category or '').strip()}"


def _product_matches_subcategory(
    product: dict[str, Any],
    *,
    category: str,
    sub_category: str,
) -> bool:
    product_category = str(product.get("category") or "").strip()
    if not product_category:
        return False
    if _normalize_text(product_category) != _normalize_text(category):
        return False
    # Empty sub-category = apply to the entire category.
    target_sub = str(sub_category or "").strip()
    if not target_sub or target_sub == "—":
        return True
    product_sub = str(product.get("sub_category") or "").strip()
    return _normalize_text(product_sub) == _normalize_text(target_sub)


def _is_lowest_make(value: str) -> bool:
    return MakeListConstraintService.is_lowest_make_selection(value)

