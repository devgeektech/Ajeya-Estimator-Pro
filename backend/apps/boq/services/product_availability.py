"""Product availability flags across Make & Vendor → Labour → Review → Export.

Single place for Not available / Not listed / Not in Db / no-labour rules so
tabs and export stay aligned without duplicated status logic.
"""
from __future__ import annotations

from typing import Any

from apps.boq.services.boq_line_output_service import BOQLineOutputService
from apps.boq.services.make_list_constraint_service import NO_APPROVED_MAKE_LABEL
from apps.boq.services.make_vendor_common import (
    NOT_AVAILABLE_LABEL,
    NOT_AVAILABLE_NOTES,
    NOT_AVAILABLE_SOURCE,
    NOT_AVAILABLE_STATUS,
    is_product_not_available,
)
from utils.timestamps import now_local_iso

# Why a product was (or will be) marked Not available.
REASON_NO_PRODUCT_ID = "no_product_id"
REASON_NOT_LISTED = "not_listed"
REASON_NOT_IN_DB = "not_in_db"
REASON_NO_LABOUR = "no_labour"

_REASON_NOTES = {
    REASON_NO_PRODUCT_ID: NOT_AVAILABLE_NOTES,
    REASON_NOT_LISTED: (
        "Not available — not listed in Make List. Rates and labour are not looked up."
    ),
    REASON_NOT_IN_DB: (
        "Not available — not in database. Rates and labour are not looked up."
    ),
    REASON_NO_LABOUR: "Not available — no labour charge found.",
}


def _selection(product: dict[str, Any] | None) -> dict[str, Any]:
    return dict((product or {}).get("vendor_selection") or {})


def _status(product: dict[str, Any] | None) -> str:
    return str(_selection(product).get("status") or "").strip().lower()


def _source(product: dict[str, Any] | None) -> str:
    item = product or {}
    selection = _selection(item)
    return str(
        item.get("vendor_selection_source") or selection.get("source") or ""
    ).strip().lower()


def is_matched(product: dict[str, Any] | None) -> bool:
    return _status(product) == "matched"


def is_not_listed(product: dict[str, Any] | None) -> bool:
    """Make list has no approved make (Make & Vendor orange — Not listed)."""
    if is_product_not_available(product) or is_matched(product):
        return False
    if _source(product) == "not_found":
        return True
    notes = str(_selection(product).get("notes") or "")
    return notes == NO_APPROVED_MAKE_LABEL or "No Approved Make" in notes


def is_not_in_db(product: dict[str, Any] | None) -> bool:
    """Product Id present but no Rate_Master row (Make & Vendor orange — Not in Db)."""
    if is_product_not_available(product) or is_not_listed(product) or is_matched(product):
        return False
    return _status(product) in {"unmatched", "pending", "not_searched", "no_match"}


def will_become_not_available_on_labour(product: dict[str, Any] | None) -> bool:
    """Analysis Not available + unresolved Make & Vendor rows → Labour Not available."""
    return (
        is_product_not_available(product)
        or is_not_listed(product)
        or is_not_in_db(product)
    )


def has_positive_labour(product: dict[str, Any] | None) -> bool:
    selection = _selection(product)
    line_output = selection.get("line_output") or {}
    labour_detail = selection.get("labour_detail")
    for value in (
        line_output.get("labour_rate"),
        line_output.get("labour_amount"),
        (labour_detail or {}).get("effective_labour_rate") if labour_detail else None,
    ):
        if value in (None, ""):
            continue
        try:
            if float(value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def will_become_not_available_on_review(product: dict[str, Any] | None) -> bool:
    """Labour Not available + matched products with no labour charge."""
    if will_become_not_available_on_labour(product) or is_product_not_available(product):
        return True
    if is_matched(product) and not has_positive_labour(product):
        return True
    return False


def mark_product_not_available(
    product: dict[str, Any],
    *,
    reason: str,
    quantity: Any = None,
) -> dict[str, Any]:
    """Persist Not available on the product; clear lookups when unresolved upstream."""
    updated = dict(product)
    selection = _selection(updated)
    notes = _REASON_NOTES.get(reason, NOT_AVAILABLE_NOTES)
    qty = (
        quantity
        if quantity not in (None, "")
        else updated.get("quantity")
        or (selection.get("line_output") or {}).get("quantity")
    )

    if reason == REASON_NO_LABOUR:
        # Keep material rates; drop labour and flag for Review/export Amount.
        line_output = dict(selection.get("line_output") or {})
        line_output["labour_rate"] = None
        line_output["labour_amount"] = None
        line_output["total_amount"] = None
        line_output["is_blank"] = True
        selection["labour_detail"] = None
        selection["line_output"] = line_output
    else:
        selection["make"] = ""
        selection["vendor"] = ""
        selection["rate_master_id"] = None
        selection["tech_key"] = ""
        selection["summary"] = ""
        selection["rate_detail"] = None
        selection["labour_detail"] = None
        selection["line_output"] = BOQLineOutputService.build(
            quantity=qty,
            rate_detail=None,
            labour_detail=None,
            is_pending=True,
            rate_only=bool(updated.get("rate_only")),
        )

    selection["status"] = NOT_AVAILABLE_STATUS
    selection["confidence"] = 0.0
    selection["notes"] = notes
    selection["not_available_reason"] = reason
    selection["prefer_lowest_price"] = False
    selection["matched_at"] = now_local_iso()
    updated["vendor_selection"] = selection
    updated["vendor_selection_source"] = NOT_AVAILABLE_SOURCE
    updated["selected_make"] = None
    updated["selected_vendor"] = None
    updated["approved_make_found"] = False
    updated["not_available_reason"] = reason
    return updated


def count_labour_confirm_buckets(analysis: dict[str, Any] | None) -> dict[str, int]:
    """Counts for Make & Vendor → Next confirm (before promotion)."""
    already = 0
    not_listed = 0
    not_in_db = 0
    for row in (analysis or {}).get("rows") or []:
        for product in row.get("products") or []:
            if is_product_not_available(product):
                already += 1
            elif is_not_listed(product):
                not_listed += 1
            elif is_not_in_db(product):
                not_in_db += 1
    return {
        "not_available_count": already,
        "not_listed_count": not_listed,
        "not_in_db_count": not_in_db,
        "will_mark_count": already + not_listed + not_in_db,
    }


def promote_unresolved_for_labour(analysis: dict[str, Any]) -> dict[str, Any]:
    """On Labour unlock: Not listed / Not in Db → Not available (skip lookups)."""
    rows = list(analysis.get("rows") or [])
    promoted = 0
    for row in rows:
        products = list(row.get("products") or [])
        if not products:
            continue
        changed = False
        updated_products: list[dict[str, Any]] = []
        for product in products:
            if is_product_not_available(product):
                updated_products.append(product)
                continue
            if is_not_listed(product):
                updated_products.append(
                    mark_product_not_available(product, reason=REASON_NOT_LISTED)
                )
                promoted += 1
                changed = True
            elif is_not_in_db(product):
                updated_products.append(
                    mark_product_not_available(product, reason=REASON_NOT_IN_DB)
                )
                promoted += 1
                changed = True
            else:
                updated_products.append(product)
        if changed:
            row["products"] = updated_products
    analysis["rows"] = rows
    return {"promoted_count": promoted, "rows": rows}


def promote_missing_labour_for_review(analysis: dict[str, Any]) -> dict[str, Any]:
    """On Labour complete: matched products with no labour → Not available."""
    rows = list(analysis.get("rows") or [])
    promoted = 0
    for row in rows:
        products = list(row.get("products") or [])
        if not products:
            continue
        changed = False
        updated_products: list[dict[str, Any]] = []
        for product in products:
            if is_product_not_available(product):
                updated_products.append(product)
                continue
            if is_matched(product) and not has_positive_labour(product):
                updated_products.append(
                    mark_product_not_available(product, reason=REASON_NO_LABOUR)
                )
                promoted += 1
                changed = True
            else:
                updated_products.append(product)
        if changed:
            row["products"] = updated_products
    analysis["rows"] = rows
    return {"promoted_count": promoted, "rows": rows}


def export_amount_value(product: dict[str, Any] | None, review_row: dict[str, Any] | None = None) -> Any:
    """Amount cell for export: literal Not available when flagged."""
    if is_product_not_available(product):
        return NOT_AVAILABLE_LABEL
    row = review_row or {}
    if str(row.get("amount") or "").strip() == NOT_AVAILABLE_LABEL:
        return NOT_AVAILABLE_LABEL
    return row.get("amount")
