"""Shape extracted products for the BOQ detail Analysis tab."""
from __future__ import annotations

import json
from typing import Any

from ai.context import load_rate_master_taxonomy
from apps.boq.models import BOQ
from apps.boq.services.boq_extraction_service import (
    quantity_display_fields,
    rehydrate_products_quantity_from_group,
)
from apps.boq.services.boq_row_fields import (
    is_blank as _is_blank,
    is_job_unit,
    resolve_activity_only,
)
from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows
from apps.boq.services.extraction_attribute_fields import COMMON_ATTRIBUTE_LABELS
from apps.boq.services.make_list_constraint_service import MakeListConstraintService
from apps.boq.services.make_vendor_common import (
    count_missing_loaded_product_ids,
    loaded_catalog_product_id,
)
from apps.boq.services.product_attribute_enrichment_service import (
    compute_attribute_confidence,
    confidence_band,
    humanize_attribute_key,
    match_percentage_band,
)
from apps.boq.services.product_matching_service import structured_match_score
from apps.database_manager.models import Rate_Master_Output
from common.constants import ANALYSIS_INPUT_FILL_CONFIDENCE
from utils.attribute_parser import coerce_attributes_dict, normalize_attribute_key


def _attribute_value_for_schema_key(
    attrs: dict[str, Any],
    schema_key: str,
) -> Any:
    """Resolve a stored attribute for a Rate_Master schema key.

    Coercion may rename keys (``PN`` → ``pressure_rating``) while the schema
    still uses the catalog label — match either form so AI-found values show.
    """
    if not schema_key:
        return None
    if schema_key in attrs and not _is_blank(attrs.get(schema_key)):
        return attrs.get(schema_key)
    key_l = str(schema_key).strip().lower()
    for raw_key, value in attrs.items():
        if str(raw_key).strip().lower() == key_l and not _is_blank(value):
            return value
    wanted = normalize_attribute_key(schema_key)
    if wanted:
        for raw_key, value in attrs.items():
            if normalize_attribute_key(str(raw_key)) == wanted and not _is_blank(value):
                return value
    return None


def _candidate_confidence_value(raw: Any) -> float | None:
    """Normalize stored retrieval/match confidence for Analysis display."""
    if raw in (None, ""):
        return None
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def _candidate_display_part(value: Any) -> str:
    """Show stored tokens as-is, including ``0``, ``null``, ``NA``, ``NB``."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return "null"
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    if not text:
        return "null"
    return text


def _candidate_attribute_bits(item: dict[str, Any]) -> list[str]:
    attrs = item.get("attributes")
    if not isinstance(attrs, dict):
        return []
    bits: list[str] = []
    for key, value in attrs.items():
        label = str(key).strip()
        if label:
            bits.append(f"{label}={_candidate_display_part(value)}")
    return bits


def _candidate_summary_for_display(
    item: dict[str, Any],
    *,
    include_empty: bool = False,
) -> str:
    """Product ID / Category / Sub / Class / Size / Unit / Capacity attrs.

    Analysis identifies catalog products by Product_ID only — never show Rate_ID.
    """
    identity: list[str] = []
    for key in (
        "product_id",
        "category",
        "sub_category",
        "class",
        "size",
        "unit",
        "capacity",
    ):
        if not include_empty and key not in item:
            continue
        identity.append(_candidate_display_part(item.get(key)))
    label = " / ".join(identity)
    attr_bits = _candidate_attribute_bits(item)
    if attr_bits:
        attrs = ", ".join(attr_bits)
        # Tab separates identity fields from Attribute key=value pairs.
        return f"{label}\t{attrs}" if label else attrs
    return label or str(item.get("summary") or "").strip() or "Matched product"


def _backfill_candidate_confidences(
    product: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    database_version_id: int | None,
) -> None:
    """Fill missing candidate % from structured score (legacy wiped scores only)."""
    if not database_version_id:
        return
    missing_ids: list[int] = []
    def _confidence_missing(raw: Any) -> bool:
        # Only fill when the score was never stored. Explicit 0.0 from retrieval
        # must stay 0 — re-scoring on Select/rematch HTML refresh made sibling
        # candidate percentages appear to jump.
        return raw is None

    for item in candidates:
        if not _confidence_missing(item.get("confidence")):
            continue
        raw_id = item.get("id")
        if raw_id is None:
            continue
        try:
            missing_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    if not missing_ids:
        return
    rates = {
        rate.pk: rate
        for rate in Rate_Master_Output.objects.filter(
            pk__in=missing_ids,
            database_version_id=database_version_id,
        )
    }
    product_only = dict(product)
    product_only["make_hint"] = None
    for item in candidates:
        if not _confidence_missing(item.get("confidence")):
            continue
        raw_id = item.get("id")
        if raw_id is None:
            continue
        try:
            cand_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        rate = rates.get(cand_id)
        if rate is None:
            continue
        score, _breakdown = structured_match_score(product_only, rate)
        item["confidence"] = round(score, 2)


def _recall_candidates_for_unmatched(
    product: dict[str, Any],
    *,
    database_version_id: int | None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """SQL-only Top-N Rate_Master neighbors when Analyse left db_candidates empty.

    Unmatched / 0% products still need Select options from description_hint.
    Never call embeddings / OpenAI here — Analysis tab GET must stay read-only.
    """
    if not database_version_id:
        return []
    hint = str(product.get("description_hint") or "").strip()
    has_identity = any(
        not _is_blank(product.get(key))
        for key in ("category", "sub_category", "class", "size", "unit", "capacity")
    )
    if not hint and not has_identity:
        return []

    from apps.boq.services.product_ai_common import _candidate_snapshot, _slim_candidate
    from apps.boq.services.product_matching_service import ProductMatchingService

    recall = {
        "description_hint": product.get("description_hint"),
        "category": product.get("category"),
        "sub_category": product.get("sub_category"),
        "class": product.get("class"),
        "size": product.get("size"),
        "unit": product.get("unit"),
        "capacity": product.get("capacity"),
        "attributes": coerce_attributes_dict(product.get("attributes")),
        "make_hint": None,
    }
    try:
        matcher = ProductMatchingService(database_version_id)
        raw_candidates = matcher.recall_sql_candidates(recall, limit=max(limit, 3))
    except Exception:
        return []

    shaped: list[dict[str, Any]] = []
    for item in raw_candidates[:limit]:
        rate = item.get("rate")
        if rate is None:
            continue
        try:
            confidence = float(item.get("structured_score") or item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        slim = _slim_candidate(_candidate_snapshot(rate, confidence=round(confidence, 2)))
        shaped.append(
            {
                "id": slim.get("id"),
                "summary": _candidate_summary_for_display(slim, include_empty=True),
                "confidence": slim.get("confidence"),
                "is_selected": False,
            }
        )
    return shaped


_PRODUCT_FIELDS: tuple[tuple[str, str], ...] = (
    ("description_hint", "AI Description"),
    ("category", "Category"),
    ("sub_category", "Sub-category"),
    ("class", "Class"),
    ("size", "Size"),
    ("unit", "Unit"),
    ("capacity", "Capacity"),
)

# All product property fields are optional — products differ in which apply.
_REQUIRED_FIELDS: frozenset[str] = frozenset()


def _attribute_label(key: str) -> str:
    return COMMON_ATTRIBUTE_LABELS.get(key) or humanize_attribute_key(key)


def _shape_attribute_fields(product: dict[str, Any]) -> dict[str, Any]:
    """
    Attributes grid = required DB schema keys only (filled when AI/expert found a value).
    Experts can add more via the Attributes + control.
    """
    attrs = coerce_attributes_dict(product.get("attributes"))
    schema_keys = [
        str(key)
        for key in (product.get("attribute_schema") or [])
        if str(key).strip()
    ]

    # Needed DB schema attributes only — never show free-form additional attributes.
    fields = []
    for key in schema_keys:
        value = _attribute_value_for_schema_key(attrs, key)
        fields.append(
            {
                "key": key,
                "label": _attribute_label(key),
                "value": "" if value is None else str(value),
                "filled": not _is_blank(value),
                "removable": False,
            }
        )

    confidence = product.get("attribute_confidence")
    if confidence is None:
        confidence = (
            compute_attribute_confidence(schema_keys, attrs)
            if schema_keys
            else 0.0
        )
    confidence = float(confidence or 0.0)
    source = product.get("attribute_source") or ("database" if schema_keys else "extracted")
    return {
        "fields": fields,
        "extra": [],
        "confidence": confidence,
        "confidence_band": confidence_band(confidence),
        "source": source,
        "has_db_schema": bool(schema_keys),
    }


def _shape_product(
    product: dict[str, Any],
    *,
    display_number: int,
    total: int,
    source_row_id: str,
    database_version_id: int | None = None,
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Show stored fields as-is. Do not wipe Class=0 or promote material on render.
    product = dict(product)
    selected_confidence = _candidate_confidence_value(
        product.get("db_match_confidence")
    )
    if selected_confidence is None:
        selected_confidence = _candidate_confidence_value(
            product.get("attribute_confidence")
        )
    stored_match_percentage = selected_confidence or 0.0
    selection_source = str(
        (product.get("ai_mapping") or {}).get("selection_source") or ""
    )
    db_match_status = str(product.get("db_match_status") or "").strip() or (
        "matched" if product.get("db_product_id") else "unmatched"
    )
    fill_threshold = float(ANALYSIS_INPUT_FILL_CONFIDENCE)

    candidates = []
    selected_id = product.get("db_product_id") or product.get("suggested_db_product_id")
    for item in (product.get("db_candidates") or [])[:3]:
        cand_id = item.get("id")
        is_selected = False
        try:
            if cand_id is not None and selected_id is not None:
                is_selected = int(cand_id) == int(selected_id)
        except (TypeError, ValueError):
            is_selected = False
        confidence = _candidate_confidence_value(item.get("confidence"))
        # Older refine passes wiped retrieval scores; still show % for the
        # selected/suggested row from the product-level match score.
        if confidence is None and is_selected:
            confidence = selected_confidence
        candidates.append(
            {
                "id": cand_id,
                "summary": _candidate_summary_for_display(item, include_empty=True)
                if (
                    item.get("product_id")
                    or item.get("category")
                    or item.get("size")
                    or item.get("unit")
                    or "class" in item
                )
                else (item.get("summary") or _product_summary(item)),
                "confidence": confidence,
                "is_selected": is_selected,
            }
        )
    # Only fill missing candidate % (legacy wiped scores). Never re-score stored
    # percentages — one product rematch must not change sibling product %.
    if selection_source != "expert":
        _backfill_candidate_confidences(
            product,
            candidates,
            database_version_id=database_version_id,
        )

    top_candidate_pct = 0.0
    for item in candidates:
        try:
            top_candidate_pct = max(
                top_candidate_pct,
                float(item.get("confidence") or 0.0),
            )
        except (TypeError, ValueError):
            continue

    # Badge should reflect the best listed neighbor when Analyse left product % at 0.
    match_percentage = stored_match_percentage
    if (
        selection_source != "expert"
        and not product.get("db_product_id")
        and top_candidate_pct > match_percentage
    ):
        match_percentage = top_candidate_pct
    match_band = match_percentage_band(match_percentage)

    # Weak banner only when effective % is below the Analysis fill threshold.
    # A 68% top candidate must not show "Unable to match…".
    # Identity fields and Attribute values stay prefilled from extract when found.
    unable_to_match = (
        selection_source != "expert"
        and match_percentage < fill_threshold
        and not product.get("db_product_id")
    )

    # Unmatched with no stored neighbors — recall live so Select is available.
    if unable_to_match and not candidates:
        candidates = _recall_candidates_for_unmatched(
            product,
            database_version_id=database_version_id,
            limit=3,
        )
        for item in candidates:
            try:
                top_candidate_pct = max(
                    top_candidate_pct,
                    float(item.get("confidence") or 0.0),
                )
            except (TypeError, ValueError):
                continue
        if top_candidate_pct > match_percentage:
            match_percentage = top_candidate_pct
            match_band = match_percentage_band(match_percentage)
            unable_to_match = (
                selection_source != "expert"
                and match_percentage < fill_threshold
                and not product.get("db_product_id")
            )

    fields: list[dict[str, Any]] = []
    missing_count = 0
    product_id_value = loaded_catalog_product_id(product)
    for key, label in _PRODUCT_FIELDS:
        if key == "category":
            fields.append(
                {
                    "key": "product_id",
                    "label": "Product Id",
                    "value": product_id_value,
                    "missing": False,
                    "readonly": True,
                }
            )
        value = product.get(key)
        missing = _is_blank(value) and key in _REQUIRED_FIELDS
        if missing:
            missing_count += 1
        fields.append(
            {
                "key": key,
                "label": label,
                "value": "" if value is None else str(value),
                "missing": missing,
                "readonly": False,
            }
        )

    attribute_fields = _shape_attribute_fields(product)
    missing_attr_keys = [
        str(key)
        for key in (product.get("missing_attribute_keys") or [])
        if str(key).strip()
    ]
    if not missing_attr_keys:
        missing_attr_keys = [
            field["key"]
            for field in attribute_fields.get("fields") or []
            if not field.get("filled")
        ]

    db_match = None
    if product.get("db_product_id") or product.get("db_product_summary") or db_match_status == "provisional":
        # Banner uses the stored DB summary — not the blanked Analysis inputs.
        summary = str(product.get("db_product_summary") or "").strip()
        if not summary:
            summary = _candidate_summary_for_display(
                {
                    "product_id": product.get("catalog_product_id")
                    or product.get("suggested_catalog_product_id"),
                    "category": product.get("category"),
                    "sub_category": product.get("sub_category"),
                    "class": product.get("class"),
                    "size": product.get("size"),
                    "unit": product.get("unit"),
                    "summary": product.get("db_product_summary"),
                }
            )
        db_match = {
            "rate_master_id": product.get("db_product_id"),
            "suggested_id": product.get("suggested_db_product_id"),
            "status": db_match_status,
            "summary": summary,
            "make": product.get("db_product_make") or "",
            "tech_key": product.get("db_product_tech_key") or "",
            "notes": ((product.get("ai_mapping") or {}).get("notes") or ""),
            "missing_attribute_keys": missing_attr_keys,
        }

    # Each product binds to its own Unit/Qty slot, so a multi-product section
    # shows different values per tab rather than the section header's figure.
    qty_fields = quantity_display_fields(product)
    weak_match_message = ""
    if unable_to_match:
        if candidates:
            weak_match_message = (
                "Unable to match this product confidently. Similar products are "
                "listed under Top database candidates — select any of them, or "
                "enter the details in the input fields below and click Re-analyse with AI."
            )
        else:
            weak_match_message = (
                "Unable to match this product confidently. Enter the details in "
                "the input fields below and click Re-analyse with AI."
            )
    return {
        "product_index": int(product.get("product_index") or 0),
        "source_row_id": source_row_id,
        "display_number": display_number,
        **qty_fields,
        "display_label": f"Product {display_number}" + (f" of {total}" if total > 1 else ""),
        "is_user_added": (product.get("source") or "").lower() == "user",
        "is_activity_only": is_job_unit(product.get("unit")) or is_job_unit(product.get("quantity_unit")),
        "catalog_product_id": product_id_value,
        "fields": fields,
        "attributes": attribute_fields,
        "extra_attrs_json": json.dumps([]),
        "attribute_schema_json": json.dumps(
            [
                field["key"]
                for field in attribute_fields.get("fields") or []
                if not field.get("removable")
            ]
        ),
        "attribute_confidence": attribute_fields["confidence"],
        "attribute_confidence_band": attribute_fields["confidence_band"],
        "match_percentage": match_percentage,
        "match_percentage_band": match_band,
        # Confirm → 100% when a product is already selected/suggested but not full credit.
        "show_confirm_match": bool(
            match_percentage < 99.5
            and (
                product.get("db_product_id")
                or product.get("suggested_db_product_id")
            )
        ),
        "show_weak_match_warning": unable_to_match,
        "show_candidates_open": bool(
            (unable_to_match or db_match_status == "unmatched") and candidates
        ),
        "weak_match_message": weak_match_message,
        "db_match": db_match,
        "db_match_status": db_match_status,
        "db_candidates": candidates,
        "missing_attribute_keys": missing_attr_keys,
        "missing_attribute_count": len(missing_attr_keys),
        "missing_count": missing_count,
        "summary": _product_summary(product),
        "raw": product,
    }


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


def _primary_category(products: list[dict[str, Any]]) -> tuple[str, str]:
    if not products:
        return "", ""
    first = products[0]
    return str(first.get("category") or ""), str(first.get("sub_category") or "")


def _shape_make_list(
    *,
    full_description: str,
    stored: dict[str, Any] | None,
    make_list_service: MakeListConstraintService,
    category: str = "",
    sub_category: str = "",
    has_make_list_file: bool = False,
) -> dict[str, Any]:
    options_data = make_list_service.make_options_for_product(
        category=category,
        sub_category=sub_category,
        description=full_description,
    )
    stored_data = stored or {}
    make_options = list(options_data.get("make_options") or [])
    if not make_options:
        make_options = make_list_service.all_approved_makes()
    for make in stored_data.get("approved_makes") or []:
        if make not in make_options:
            make_options.append(make)

    selected = stored_data.get("selected_make") or ""
    prefer_lowest = bool(stored_data.get("prefer_lowest_price")) or (
        MakeListConstraintService.is_lowest_make_selection(selected)
    )
    if not make_list_service.has_constraints and not selected:
        prefer_lowest = True
    is_custom = (not prefer_lowest) and (
        bool(stored_data.get("custom_make"))
        or (selected and selected not in make_options)
    )
    return {
        "has_make_list": has_make_list_file and bool(make_list_service.has_constraints or make_options),
        "matched": bool(options_data.get("matched") or stored_data),
        "material": stored_data.get("material") or options_data.get("material") or "",
        "category_material": options_data.get("category_material") or "",
        "mapped_category": options_data.get("mapped_category") or category or "",
        "selection_basis": options_data.get("selection_basis") or "",
        "approved_makes": make_options,
        "make_options": make_options,
        "selected_make": selected,
        "custom_make": stored_data.get("custom_make") or (selected if is_custom else ""),
        "is_custom_make": is_custom,
        "is_lowest_make": prefer_lowest,
        "prefer_lowest_price": prefer_lowest,
        "match_score": stored_data.get("match_score") or options_data.get("match_score"),
    }


def _product_boq_order_key(product: dict[str, Any]) -> tuple[int, int]:
    """Sort key: BOQ qty slot order, then stored product_index (never match %)."""
    raw_slot = product.get("slot_index")
    try:
        slot = int(raw_slot) if raw_slot not in (None, "") else 10**9
    except (TypeError, ValueError):
        slot = 10**9
    try:
        index = int(product.get("product_index") or 0)
    except (TypeError, ValueError):
        index = 0
    return (slot, index)


def _merge_lineage_analysis(
    lineage_ids: list[str],
    analysis_by_row: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    anchor_id = lineage_ids[0] if lineage_ids else ""
    anchor_analysis = analysis_by_row.get(anchor_id, {})

    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_id in lineage_ids:
        analysis_row = analysis_by_row.get(row_id, {})
        for product in analysis_row.get("products") or []:
            dedupe_key = "|".join(
                [
                    str(product.get("description_hint") or ""),
                    str(product.get("category") or ""),
                    str(product.get("sub_category") or ""),
                    str(product.get("product_index") or ""),
                    str(product.get("slot_index") or ""),
                ]
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            products.append({**product, "source_row_id": row_id})

    # Keep BOQ / slot sequence — do not arrange tabs by match percentage.
    products.sort(key=_product_boq_order_key)
    # Preserve stored product_index for rematch/edit; display_number is visual only.

    # Activities are retired — Analysis extracts products only.
    return products, [], anchor_analysis


def build_product_save_feedback(product: dict[str, Any]) -> dict[str, Any]:
    """Return UI feedback fields after saving a product."""
    shaped = _shape_product(
        product,
        display_number=int(product.get("product_index") or 0) + 1,
        total=1,
        source_row_id=str(product.get("source_row_id") or ""),
        database_version_id=None,
    )
    return {
        "missing_count": shaped["missing_count"],
        "summary": shaped["summary"],
        "is_complete": shaped["missing_count"] == 0,
        "attribute_confidence": shaped["attribute_confidence"],
        "attribute_confidence_band": shaped["attribute_confidence_band"],
        "match_percentage": shaped["match_percentage"],
        "match_percentage_band": shaped["match_percentage_band"],
    }


class BOQExtractionDisplayService:
    """Build upload-order rows showing AI-extracted products."""

    def __init__(self, boq: BOQ, make_list_data: dict | None = None, *, has_make_list_file: bool = False):
        self.boq = boq
        self.has_make_list_file = has_make_list_file
        self.make_list_service = MakeListConstraintService(make_list_data)

    def build(self) -> dict[str, Any]:
        analysis = self.boq.analysis_data or {}
        boq_data = self.boq.boq_data or {}
        analysis_by_row = {
            str(row.get("row_id")): row
            for row in analysis.get("rows") or []
            if row.get("row_id")
        }

        lines: list[dict[str, Any]] = []
        product_count = 0
        missing_field_count = 0
        multiproduct_review_count = 0

        db_version_id = int((analysis.get("database_version_id") or 0) or 0) or None
        if not db_version_id:
            from apps.database_manager.services.activation import get_active_database_version

            active = get_active_database_version()
            db_version_id = active.pk if active else None
        taxonomy = load_rate_master_taxonomy(db_version_id)

        for group in grouped_anchor_rows(boq_data):
            row_id = group["row_id"]
            products, _activities, analysis_row = _merge_lineage_analysis(
                group["group_ids"],
                analysis_by_row,
            )
            # Restore slot qty when products kept qty_row_id but lost quantity.
            products = rehydrate_products_quantity_from_group(products, group)
            product_total = len(products)
            qty_rows = list(group.get("qty_rows") or [])
            qty_row_count = int(group.get("slot_count") or 0) or len(
                group.get("slots") or qty_rows
            )
            qty = group.get("qty")
            unit = group.get("unit")
            if qty in (None, "") and qty_rows:
                qty = qty_rows[0].get("qty")
                unit = unit or qty_rows[0].get("unit")

            is_activity_only = resolve_activity_only(
                analysis_row,
                products=products,
                units=[
                    unit,
                    group.get("unit"),
                    *[row.get("unit") for row in qty_rows],
                ],
            )

            if is_activity_only:
                shaped_products = []
                product_total = 0
                multiproduct_review = False
                confidence_border = None
                status = "extracted"
            else:
                multiproduct_review = (
                    qty_row_count > 0
                    and product_total > 0
                    and product_total != qty_row_count
                )

                shaped_products = [
                    _shape_product(
                        product,
                        display_number=index + 1,
                        total=product_total,
                        source_row_id=str(product.get("source_row_id") or row_id),
                        database_version_id=db_version_id,
                        taxonomy=taxonomy,
                    )
                    for index, product in enumerate(products)
                ]
                product_count += len(products)
                missing_field_count += sum(product["missing_count"] for product in shaped_products)
                if multiproduct_review:
                    multiproduct_review_count += 1

                if analysis_row.get("skip_matching") and not products:
                    status = "skipped"
                elif products:
                    status = "extracted"
                elif analysis_row:
                    status = "empty"
                else:
                    status = "not_analyzed"

                if multiproduct_review or not shaped_products:
                    confidence_border = None
                else:
                    is_all_green = all(
                        str(p.get("match_percentage_band") or "").strip() == "green"
                        for p in shaped_products
                    )
                    confidence_border = "green" if is_all_green else "red"
            category, sub_category = _primary_category(products)

            # Hide pure chapter headers with no Unit/Qty slots and no products.
            # Keep empty sections that have qty slots so experts can Add / Re-analyse.
            if (
                status == "skipped"
                and analysis_row.get("skip_reason") != "ai_missing_row"
                and qty_row_count == 0
            ):
                continue
            if (
                not products
                and qty_row_count == 0
                and status in {"skipped", "not_analyzed", "empty"}
            ):
                continue

            qty = group.get("qty")
            unit = group.get("unit")
            qty_status = str(group.get("qty_status") or "empty")
            # Fall back to first Unit/Qty slot when group header qty was missing.
            if qty in (None, "") and qty_rows:
                qty = qty_rows[0].get("qty")
                unit = unit or qty_rows[0].get("unit")
                qty_status = str(qty_rows[0].get("qty_status") or qty_status)
            show_qty_unit = qty_status in {"numeric", "zero", "rate_only", "multi"} or qty not in (
                None,
                "",
            )
            if show_qty_unit and qty in (None, ""):
                qty_display = "—"
            elif show_qty_unit:
                qty_display = str(qty)
            else:
                qty_display = ""
            unit_display = str(unit).strip() if unit not in (None, "") else "—"

            lines.append(
                {
                    "row_id": row_id,
                    "serial": group.get("serial", ""),
                    "depth": group.get("depth", 0),
                    "description": group.get("description") or "",
                    "full_description": group.get("full_description") or group.get("description") or "",
                    "lineage_parts": group.get("lineage_parts") or [],
                    "lineage_count": group.get("lineage_count") or 1,
                    "primary_category": category,
                    "primary_sub_category": sub_category,
                    "qty": qty,
                    "unit": unit,
                    "qty_display": qty_display,
                    "unit_display": unit_display,
                    "show_qty_unit": show_qty_unit,
                    "qty_status": qty_status,
                    "qty_row_count": qty_row_count,
                    "slot_count": int(group.get("slot_count") or qty_row_count),
                    "rate_only": bool(group.get("rate_only")),
                    "boq_rate": group.get("boq_rate"),
                    "status": status,
                    "skip_reason": analysis_row.get("skip_reason") or "",
                    "product_count": product_total,
                    "multiproduct_review": multiproduct_review,
                    "is_activity_only": is_activity_only,
                    "needs_product": product_total == 0 and qty_row_count > 0,
                    "products": shaped_products,
                    "confidence_border": confidence_border,
                    "make_list": _shape_make_list(
                        full_description=group.get("full_description") or "",
                        stored=analysis_row.get("make_list"),
                        make_list_service=self.make_list_service,
                        category=category,
                        sub_category=sub_category,
                        has_make_list_file=self.has_make_list_file,
                    ),
                }
            )

        stats = analysis.get("stats") or {}
        missing_product_id_count = count_missing_loaded_product_ids(analysis)
        return {
            "has_extraction": bool(analysis.get("rows")),
            "phase": analysis.get("phase"),
            "stats": stats,
            "product_count": product_count,
            "missing_field_count": missing_field_count,
            "missing_product_id_count": missing_product_id_count,
            "matched_product_id_count": max(0, product_count - missing_product_id_count),
            "multiproduct_review_count": multiproduct_review_count,
            "has_make_list": self.has_make_list_file and self.make_list_service.has_constraints,
            "lines": lines,
        }
