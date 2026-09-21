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
from utils.nominal_size import nominal_sizes_compatible

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
    for match in _IS_STANDARD_NUMBER.finditer(text or ""):
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


_TEMP_ATTR_KEYS = ("temp", "operating_temp", "temperature", "operating_temperature")


def _fill_operating_temp_attribute(
    attrs: dict[str, Any],
    *,
    blob: str,
) -> bool:
    """Promote ``Operating Temp. : 68 deg.C.`` into a temp attribute when blank."""
    from utils.nominal_size import parse_operating_temp_from_text

    temp = parse_operating_temp_from_text(blob)
    if not temp:
        return False
    for key in _TEMP_ATTR_KEYS:
        if key in attrs and not _is_blank_value(attrs.get(key)):
            return False
    target = "temp"
    for key in _TEMP_ATTR_KEYS:
        if key in attrs:
            target = key
            break
    attrs[target] = temp
    return True


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
    changed = _fill_operating_temp_attribute(attrs, blob=blob)

    if not attrs:
        if changed:
            item["attributes"] = attrs
        return item

    is_numbers = _is_standard_numbers_in_text(blob)
    for key, value in list(attrs.items()):
        if _is_blank_value(value):
            continue
        key_norm = key.strip().lower()
        if key_norm in {"is", "is_standard"}:
            digits = re.sub(r"[^0-9]", "", value)
            if not digits or digits not in is_numbers:
                del attrs[key]
                changed = True
            continue
        if key_norm in _TEMP_ATTR_KEYS:
            if not _value_in_evidence(value, blob):
                del attrs[key]
                changed = True
            continue
        if not _value_in_evidence(value, blob):
            del attrs[key]
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


def _reconcile_size_from_slot_evidence(
    product: dict[str, Any],
    *,
    slot_desc: str,
    product_context: str,
    category: Any = None,
    sub_category: Any = None,
    pattern: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prefer size parsed from the Unit/Qty slot line over wrong AI copies.

    Operating-temp slots (``i) Operating Temp. : 68 deg.C.``) have no nominal
    size on the qty line — fall through to ``product_context`` (``15 mm``).
    """
    from utils.nominal_size import is_performance_spec_number, parse_operating_temp_from_text

    item = dict(product)
    slot_blob = (slot_desc or "").strip()
    prefer_context_first = bool(
        slot_blob
        and parse_operating_temp_from_text(slot_blob)
        and not re.search(r"(?i)\d+(?:\.\d+)?\s*(?:mm|nb|dia(?:meter)?)\b", slot_blob)
    )
    texts = (
        (product_context, slot_desc)
        if prefer_context_first
        else (slot_desc, product_context)
    )
    for text in texts:
        blob = (text or "").strip()
        if not blob:
            continue
        size, unit = parse_size_for_product(
            blob,
            category=category or item.get("category"),
            sub_category=sub_category or item.get("sub_category"),
            pattern=pattern,
            require_explicit_unit=True,
        )
        if not size:
            continue
        if is_performance_spec_number(blob, size):
            continue
        current = item.get("size")
        if _is_blank_value(current) or not nominal_sizes_compatible(current, size):
            item["size"] = size
            if unit:
                from utils.catalog_size_rules import snap_unit_to_pattern

                item["unit"] = snap_unit_to_pattern(unit, pattern) or unit
        break
    return item


def _fill_unit_from_size_evidence(
    product: dict[str, Any],
    *,
    evidence_text: str,
    pattern: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """When Size is known but Unit was missed, recover mm/NB/m from evidence."""
    item = dict(product)
    if _is_blank_value(item.get("size")) or not _is_blank_value(item.get("unit")):
        return item
    size_text = str(item.get("size") or "").strip()
    blob = (evidence_text or "")
    if not size_text or not blob:
        return item
    match = re.search(
        rf"(?i)(?<![0-9]){re.escape(size_text)}\s*(mm|nb|inch|in|cm|m)\b",
        blob,
    )
    if not match:
        match = re.search(r"(?i)(?<![0-9])\d+(?:\.\d+)?\s*(mm|nb|inch|in|cm)\b", blob)
    if not match:
        return item
    unit_token = match.group(1).lower()
    unit = {"nb": "NB", "in": "inch"}.get(unit_token, unit_token)
    from utils.catalog_size_rules import snap_unit_to_pattern

    item["unit"] = snap_unit_to_pattern(unit, pattern) or unit
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
    item = normalize_main_product_identity(item, evidence_text=blob, taxonomy=taxonomy)
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
    # Slot letter line wins after catalog unit checks (mm↔nb must not wipe Size).
    # Temp-only slots prefer product_context (parent ``15 mm``) over ``68 deg``.
    item = _reconcile_size_from_slot_evidence(
        item,
        slot_desc=slot_desc,
        product_context=product_context,
        category=item.get("category"),
        sub_category=item.get("sub_category"),
        pattern=pattern,
    )
    from utils.catalog_size_rules import snap_unit_to_pattern
    from utils.nominal_size import (
        is_performance_spec_number,
        parse_operating_temp_from_text,
        sanitize_product_size,
    )

    if not _is_blank_value(item.get("size")) and pattern:
        snapped = snap_unit_to_pattern(item.get("unit"), pattern)
        if snapped:
            item["unit"] = snapped

    item = sanitize_product_size(
        item,
        extra_texts=[product_context, slot_desc, evidence_text, section_text],
        use_description_hint=False,
    )
    if _is_blank_value(item.get("size")):
        # Prefer nominal size from owning context when the qty line is temp-only.
        slot_blob = (slot_desc or "").strip()
        temp_only_slot = bool(
            slot_blob
            and parse_operating_temp_from_text(slot_blob)
            and not re.search(r"(?i)\d+(?:\.\d+)?\s*(?:mm|nb|dia(?:meter)?)\b", slot_blob)
        )
        refill_blob = (
            _evidence_blob(product_context, evidence_text)
            if temp_only_slot
            else (slot_blob or _evidence_blob(product_context, evidence_text))
        )
        refill_pattern = pattern_for_product(item, patterns) if patterns else pattern_for_product(item)
        size, unit = parse_size_for_product(
            refill_blob,
            category=item.get("category"),
            sub_category=item.get("sub_category"),
            pattern=refill_pattern,
            require_explicit_unit=True,
        )
        if size and not is_performance_spec_number(refill_blob, size):
            item["size"] = size
            if unit:
                item["unit"] = snap_unit_to_pattern(unit, refill_pattern) or unit

    item = _fill_unit_from_size_evidence(
        item,
        evidence_text=_evidence_blob(product_context, slot_desc, evidence_text),
        pattern=pattern,
    )
    return item
