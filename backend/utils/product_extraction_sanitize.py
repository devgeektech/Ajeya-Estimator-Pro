"""Clear uncertain AI-extracted product fields; never substitute guesses."""
from __future__ import annotations

import re
from typing import Any

from ai.context import is_catalog_class, load_rate_master_taxonomy, resolve_class_label, snap_product_taxonomy
from apps.boq.services.boq_row_fields import is_blank as _is_blank_value
from utils.attribute_parser import coerce_attributes_dict
from utils.catalog_size_rules import (
    normalize_catalog_size_capacity,
    normalize_main_product_identity,
    parse_box_capacity_from_text,
    parse_size_for_product,
    pattern_for_product,
    validate_size_unit_for_pattern,
)

_PN_RATING = re.compile(r"(?i)\bPN\s*(\d+)\b")
_IS_STANDARD_NUMBER = re.compile(
    r"(?i)\bis\s*:?\s*(\d{2,6})(?:\s*[-/]\s*(\d{2,4}))?"
)


def _evidence_blob(*parts: Any) -> str:
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip()).strip()


def _parse_pn_capacity(text: Any) -> str | None:
    match = _PN_RATING.search(str(text or ""))
    if not match:
        return None
    return f"PN{match.group(1)}"


def _is_standard_numbers_in_text(text: str) -> set[str]:
    """Primary IS standard numbers only (exclude publication year suffix)."""
    numbers: set[str] = set()
    for match in _IS_STANDARD_NUMBER.finditer(str(text or "")):
        numbers.add(match.group(1))
    return numbers


def _value_in_evidence(value: Any, blob: str) -> bool:
    raw = str(value or "").strip()
    if not raw or not blob:
        return False
    blob_cf = blob.casefold()
    if raw.casefold() in blob_cf:
        return True
    compact = re.sub(r"[^0-9a-zA-Z]+", "", raw).casefold()
    if compact and compact in re.sub(r"[^0-9a-zA-Z]+", "", blob).casefold():
        return True
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", raw.casefold())
        if len(token) >= 2
    ]
    if tokens and all(token in blob_cf for token in tokens):
        return True
    return False


def _sanitize_capacity(
    product: dict[str, Any],
    *,
    product_context: str,
    slot_desc: str,
    evidence_text: str,
) -> dict[str, Any]:
    """Fill PN capacity only from owning evidence; clear wrong guesses."""
    item = dict(product)
    blob = _evidence_blob(product_context, slot_desc, evidence_text)
    context_pn = _parse_pn_capacity(product_context) or _parse_pn_capacity(evidence_text)
    current = item.get("capacity")

    if _is_blank_value(current):
        if context_pn:
            item["capacity"] = context_pn
        return item

    current_pn = _parse_pn_capacity(current)
    if context_pn:
        if current_pn and current_pn != context_pn:
            item["capacity"] = None
        elif not current_pn and not _value_in_evidence(current, blob):
            item["capacity"] = None
    elif current_pn and not _value_in_evidence(current_pn, blob):
        item["capacity"] = None
    elif not _value_in_evidence(current, blob):
        item["capacity"] = None
    return item


def _sanitize_make_hint(
    product: dict[str, Any],
    *,
    product_context: str,
    slot_desc: str,
    evidence_text: str,
) -> dict[str, Any]:
    item = dict(product)
    hint = item.get("make_hint")
    if _is_blank_value(hint):
        return item
    blob = _evidence_blob(product_context, slot_desc, evidence_text)
    if not _value_in_evidence(hint, blob):
        item["make_hint"] = None
    return item


def _sanitize_attributes(
    product: dict[str, Any],
    *,
    product_context: str,
    slot_desc: str,
    evidence_text: str,
) -> dict[str, Any]:
    """Drop attribute values not supported by BOQ evidence (esp. IS numbers)."""
    item = dict(product)
    attrs = coerce_attributes_dict(item.get("attributes"))
    blob = _evidence_blob(product_context, slot_desc, evidence_text)
    if not attrs:
        return item

    is_numbers = _is_standard_numbers_in_text(blob)
    changed = False
    for key, value in list(attrs.items()):
        if _is_blank_value(value):
            continue
        key_norm = str(key).strip().lower()
        if key_norm in {"is", "is_standard"}:
            digits = re.sub(r"[^0-9]", "", str(value))
            if not digits or digits not in is_numbers:
                attrs[key] = None
                changed = True
            continue
        if not _value_in_evidence(value, blob):
            attrs[key] = None
            changed = True

    if changed:
        item["attributes"] = attrs
    return item


def _sanitize_class(
    product: dict[str, Any],
    *,
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Clear class when it does not map to the Rate_Master list for cat/sub."""
    item = dict(product)
    class_value = item.get("class")
    if _is_blank_value(class_value):
        return item
    taxonomy = taxonomy or load_rate_master_taxonomy()
    category = item.get("category")
    sub_category = item.get("sub_category")
    if is_catalog_class(
        class_value,
        category=category,
        sub_category=sub_category,
        taxonomy=taxonomy,
    ):
        return item
    resolved = resolve_class_label(
        str(class_value),
        category=str(category or "").strip() or None,
        sub_category=str(sub_category or "").strip() or None,
        classes_by_category_sub_category=dict(
            taxonomy.get("classes_by_category_sub_category") or {}
        ),
    )
    if resolved:
        item["class"] = resolved
    else:
        item["class"] = None
    return item


def _sanitize_size_and_capacity_for_catalog(
    product: dict[str, Any],
    *,
    product_context: str,
    slot_desc: str,
    evidence_text: str,
    size_patterns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Align Size/Unit/Capacity with Product_Helper patterns for this family."""
    item = dict(product)
    blob = _evidence_blob(product_context, slot_desc, evidence_text)
    pattern = pattern_for_product(item, size_patterns)
    item = validate_size_unit_for_pattern(
        item,
        evidence_text=blob,
        pattern=pattern,
    )

    cat_sub = (
        str(item.get("category") or "").strip().upper(),
        str(item.get("sub_category") or "").strip().upper(),
    )
    if cat_sub == ("HYDRANT", "FIRE HOSE BOX"):
        box_capacity = parse_box_capacity_from_text(blob)
        if box_capacity and _is_blank_value(item.get("capacity")):
            item["capacity"] = box_capacity
        if _is_blank_value(item.get("size")):
            item["size"] = None
        if str(item.get("unit") or "").strip().lower() == "mm" and _is_blank_value(
            item.get("size")
        ):
            item["unit"] = None
    return item


def sanitize_product_against_evidence(
    product: dict[str, Any],
    *,
    product_context: str = "",
    slot_desc: str = "",
    evidence_text: str = "",
    section_text: str = "",
    taxonomy: dict[str, Any] | None = None,
    size_patterns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Validate AI extraction against BOQ evidence; null fields that are guesses.

    Authoritative sources: ``product_context``, slot description, slot evidence.
    Never fills from ``description_hint`` (AI output).
    """
    item = dict(product)
    item = snap_product_taxonomy(item, taxonomy, infer_defaults=False)
    blob = _evidence_blob(product_context, slot_desc, evidence_text)
    item = normalize_main_product_identity(item, evidence_text=blob)
    item = _sanitize_capacity(
        item,
        product_context=product_context,
        slot_desc=slot_desc,
        evidence_text=evidence_text,
    )
    item = _sanitize_make_hint(
        item,
        product_context=product_context,
        slot_desc=slot_desc,
        evidence_text=evidence_text,
    )
    item = _sanitize_attributes(
        item,
        product_context=product_context,
        slot_desc=slot_desc,
        evidence_text=evidence_text,
    )
    item = _sanitize_class(item, taxonomy=taxonomy)
    patterns = [] if size_patterns is None else size_patterns
    pattern = pattern_for_product(item, patterns) if patterns else pattern_for_product(item)
    blob = _evidence_blob(product_context, slot_desc, evidence_text)
    item = normalize_catalog_size_capacity(item, pattern=pattern, evidence_text=blob)
    if patterns:
        item = _sanitize_size_and_capacity_for_catalog(
            item,
            product_context=product_context,
            slot_desc=slot_desc,
            evidence_text=evidence_text,
            size_patterns=patterns,
        )
    from utils.nominal_size import sanitize_product_size

    item = sanitize_product_size(
        item,
        extra_texts=[product_context, slot_desc, evidence_text, section_text],
        use_description_hint=False,
    )
    if _is_blank_value(item.get("size")):
        refill_blob = _evidence_blob(product_context, slot_desc, evidence_text)
        refill_pattern = pattern_for_product(item, patterns) if patterns else pattern_for_product(item)
        size, unit = parse_size_for_product(
            refill_blob,
            category=item.get("category"),
            sub_category=item.get("sub_category"),
            pattern=refill_pattern,
            require_explicit_unit=True,
        )
        if size:
            item["size"] = size
            if unit:
                item["unit"] = unit
    return item
