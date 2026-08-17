"""Slot evidence binding and section attribute sharing for BOQ extraction."""
from __future__ import annotations

import logging
import re
from typing import Any

from ai.context import snap_product_taxonomy
from apps.boq.services.boq_extraction_fields import (
    _apply_one_qty,
    _is_placeholder_class,
    _is_qty_uom,
    normalize_product_fields,
)
from apps.boq.services.boq_row_fields import is_blank as _is_blank_value
from apps.boq.services.serial_normalizer import letter_from_serial
from utils.attribute_parser import coerce_attributes_dict
from apps.boq.services.extraction_attribute_fields import COMMON_ATTRIBUTE_LABELS
from apps.boq.services.product_attribute_enrichment_service import (
    humanize_attribute_key,
)

logger = logging.getLogger("boq_ai")


# Prefer these attribute keys first in AI Description (then any other filled attrs).
_DESCRIPTION_ATTR_PRIORITY: tuple[str, ...] = (
    "is",
    "type",
    "material",
    "body_material",
    "connection_type",
    "outlet_type",
    "mounting",
    "pressure_rating",
    "fire_rating",
    "seat_type",
    "end_connection",
    "spindle_type",
    "rating",
)

_SIZE_FROM_TEXT = re.compile(
    r"(?i)(?:^|[^0-9])(\d+(?:\.\d+)?)\s*(mm|nb|inch|in|cm)?\b"
)


_PN_RATING_FROM_TEXT = re.compile(r"(?i)\bPN\s*[- ]?\s*(\d+)\b")


_SHARED_SECTION_ATTR_KEYS = frozenset(
    {
        "is",
        "seat_type",
        "connection_type",
        "material",
        "body_material",
        "spindle_type",
        "rating",
        "pressure_rating",
        "end_connection",
    }
)


_SPEC_KEYWORDS = frozenset(
    {
        "speed",
        "capacity",
        "head",
        "pressure",
        "flow",
        "power",
        "voltage",
        "rpm",
        "efficiency",
        "dimension",
        "size",
        "weight",
        "model",
        "type",
    }
)


_SPEC_LABEL_ONLY = re.compile(
    r"^(?P<label>speed|capacity|head|pressure|flow|power|voltage|rpm|efficiency|"
    r"dimension|size|weight|model|type)"
    r"(?:\s*\([^)]*\))?"
    r"(?:\s*:.*)?$",
    re.IGNORECASE,
)


_SIZE_ONLY_HINT = re.compile(
    r"(?i)^\s*(?:[a-z]\)?\s*)?\d+(?:\.\d+)?\s*(?:mm|nb|inch|in|cm)?\s*(?:dia(?:meter)?)?\s*$"
)


def _is_spec_only_product(product: dict[str, Any]) -> bool:
    """Drop spec-label rows the model may still return as products."""
    if product.get("slot_fallback"):
        return False
    hint = str(product.get("description_hint") or "").strip()
    if not hint:
        return False
    if _SPEC_LABEL_ONLY.fullmatch(hint):
        return True
    if ":" in hint:
        label = hint.split(":", 1)[0].strip().lower()
        if label in _SPEC_KEYWORDS:
            return True
    return False


def _product_slot_identity(product: dict[str, Any]) -> tuple[str, str, str, str]:
    """Same BOQ product on the same slot — used to drop duplicate extracts."""
    hint = re.sub(
        r"\s+",
        " ",
        str(product.get("description_hint") or "").strip().lower(),
    )
    return (
        hint,
        str(product.get("category") or "").strip().lower(),
        str(product.get("sub_category") or "").strip().lower(),
        str(product.get("size") or "").strip().lower(),
    )


def _qty_rank(product: dict[str, Any]) -> float:
    """Prefer the copy that kept the BOQ slot quantity."""
    raw = product.get("quantity")
    if raw in (None, ""):
        return -1.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        text = str(raw).strip().lower()
        if text in {"rate only", "ro"}:
            return 0.0
        return -1.0


def _collapse_duplicate_slot_products(
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one product when AI emitted the same item twice on one Unit/Qty slot."""
    if len(products) <= 1:
        return products
    kept: list[dict[str, Any]] = []
    seen: dict[tuple[str, tuple[str, str, str, str]], int] = {}
    for product in products:
        item = dict(product)
        slot_id = str(item.get("qty_row_id") or item.get("source_row_id") or "")
        identity = _product_slot_identity(item)
        if not identity[0]:
            kept.append(item)
            continue
        key = (slot_id, identity)
        prior_index = seen.get(key)
        if prior_index is None:
            seen[key] = len(kept)
            kept.append(item)
            continue
        if _qty_rank(item) > _qty_rank(kept[prior_index]):
            kept[prior_index] = item
    for index, item in enumerate(kept):
        item["product_index"] = index
    return kept


def _filter_spec_products(
    products: list[dict[str, Any]],
    *,
    taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    filtered = [product for product in products if not _is_spec_only_product(product)]
    cleaned: list[dict[str, Any]] = []
    for index, product in enumerate(filtered):
        product = dict(product)
        product["product_index"] = index
        attrs = coerce_attributes_dict(product.get("attributes"))
        product["attributes"] = attrs
        for key in ("category", "sub_category", "class", "size", "unit", "capacity", "make_hint"):
            if key in product and product.get(key) is not None and str(product.get(key)).strip() == "":
                product[key] = None
        product = snap_product_taxonomy(product, taxonomy)
        cleaned.append(normalize_product_fields(product, preserve_class=True))
    return cleaned


def _parse_size_from_text(text: Any) -> tuple[str | None, str | None]:
    """
    Return (size, measurement_unit) from BOQ letter/size text.

    Prefers the first clear nominal size (e.g. ``200`` from ``200mm dia``).
    """
    blob = str(text or "").strip()
    if not blob:
        return None, None
    match = _SIZE_FROM_TEXT.search(blob)
    if not match:
        return None, None
    size = match.group(1)
    try:
        number = float(size)
        if number.is_integer():
            size = str(int(number))
    except ValueError:
        pass
    unit_token = (match.group(2) or "").strip().lower()
    unit = None
    if unit_token in {"mm", "cm", "nb"}:
        unit = "NB" if unit_token == "nb" else unit_token
    elif unit_token in {"inch", "in"}:
        unit = "inch"
    elif re.search(r"(?i)\bmm\b", blob):
        unit = "mm"
    return size, unit


def _parse_pn_capacity(text: Any) -> str | None:
    match = _PN_RATING_FROM_TEXT.search(str(text or ""))
    if not match:
        return None
    return f"PN{match.group(1)}"


def _section_product_noun(section_text: str) -> str:
    """Pull a short product noun from parent BOQ text for weak size-only hints.

    Prefer the purchasable family (pipe / valve) over incidental system names
    like ``Yard Hydrant System`` that appear before ``MS Pipe``.
    """
    blob = str(section_text or "").strip()
    if not blob:
        return ""
    priority_patterns = (
        r"(?i)\b(sluice\s+valve|butterfly\s+valve|ball\s+valve|gate\s+valve|"
        r"non[\s-]?return\s+valve|check\s+valve|y[\s-]?strainer|strainer|"
        r"landing\s+valve|hose\s+reel|sprinkler|fire\s+pump|jockey\s+pump|"
        r"pressure\s+switch|flow\s+switch|ms\s+pipe|gi\s+pipe)\b",
        r"(?i)\b(pipework|piping|pipes?)\b",
        r"(?i)\b(hydrant)\b",
    )
    for pattern in priority_patterns:
        match = re.search(pattern, blob)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def _normalize_hint_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _is_raw_slot_paste(hint: str, slot_desc: str) -> bool:
    """True when AI copied the Unit/Qty row instead of writing an understanding."""
    hint_norm = _normalize_hint_text(hint)
    slot_norm = _normalize_hint_text(slot_desc)
    if not hint_norm or not slot_norm:
        return False
    if hint_norm == slot_norm:
        return True
    # Slot is size-only and hint is essentially that size line.
    if _SIZE_ONLY_HINT.match(slot_desc) and (
        hint_norm == slot_norm or _SIZE_ONLY_HINT.match(hint)
    ):
        return True
    return False


def _format_description_attributes(
    attributes: Any,
    *,
    limit: int = 4,
) -> str:
    """Short attribute phrases for AI Description (IS, Type, Material, …)."""
    attrs = coerce_attributes_dict(attributes)
    if not attrs:
        return ""
    ordered_keys: list[str] = []
    seen: set[str] = set()
    for key in _DESCRIPTION_ATTR_PRIORITY:
        if key in attrs and key not in seen:
            ordered_keys.append(key)
            seen.add(key)
    for key in sorted(attrs.keys(), key=lambda item: str(item).lower()):
        norm = str(key).strip().lower()
        if norm and norm not in seen:
            ordered_keys.append(norm)
            seen.add(norm)
    parts: list[str] = []
    for key in ordered_keys:
        raw = attrs.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        label = COMMON_ATTRIBUTE_LABELS.get(key) or humanize_attribute_key(key)
        # "IS Standard 903" reads better than "is standard 903" mid-sentence.
        label_text = "IS" if label.strip().lower() in {"is", "is standard"} else label.lower()
        parts.append(f"{label_text} {value}")
        if len(parts) >= limit:
            break
    return ", ".join(parts)


def _trim_number(value: str) -> str:
    """``1.00`` → ``1`` so sizes read naturally."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".")[0]
    if re.fullmatch(r"\d+\.\d*?[1-9]0+", text):
        return text.rstrip("0")
    return text


def _natural_size_phrase(size: Any, unit: Any) -> str:
    size_text = _trim_number(size)
    if not size_text:
        return ""
    unit_text = str(unit or "").strip()
    if not unit_text:
        return size_text
    if unit_text.lower() == "mm":
        return f"{size_text} mm dia"
    return f"{size_text} {unit_text}"


def _natural_capacity_phrase(capacity: Any) -> str:
    text = _trim_number(capacity)
    if not text or text in {"0", "0.0", "0.00"}:
        return ""
    if re.match(r"(?i)^pn\s*\d+$", text):
        return text.upper().replace(" ", "")
    return f"capacity {text}"


def compose_description_hint(product: dict[str, Any]) -> str:
    """Write AI Description as one natural-language product line.

    Mentions Class, Sub-category, Category, Size, Unit, Capacity and a few
    attributes, e.g.
    ``SS branch pipe for hydrant, 20 mm dia, with is standard 903, type short
    branch pipe``.
    """
    category = str(product.get("category") or "").strip()
    sub_category = str(product.get("sub_category") or "").strip()
    product_class = str(product.get("class") or "").strip()

    noun = (sub_category or category).lower()
    if not noun:
        return ""
    lead_words = []
    if product_class and product_class not in {"0", "0.0"}:
        lead_words.append(product_class)
    lead_words.append(noun)
    lead = " ".join(lead_words)
    if sub_category and category and category.lower() not in sub_category.lower():
        lead = f"{lead} for {category.lower()}"

    details: list[str] = []
    size_phrase = _natural_size_phrase(product.get("size"), product.get("unit"))
    if size_phrase:
        details.append(size_phrase)
    capacity_phrase = _natural_capacity_phrase(product.get("capacity"))
    if capacity_phrase:
        details.append(capacity_phrase)
    attr_text = _format_description_attributes(product.get("attributes"))
    if attr_text:
        details.append(f"with {attr_text}")

    sentence = lead if not details else f"{lead}, {', '.join(details)}"
    return sentence[:500]


def _enrich_description_hint(
    product: dict[str, Any],
    *,
    section_text: str,
    slot_desc: str,
) -> str:
    """Prefer taxonomy + attributes; fall back to AI prose / synthetic noun+size.

    Experts see ``description_hint`` as AI Description. When Category / Sub-category
    (or other core fields) are present, compose them into one line so the field
    always mentions Category, Sub-category, Class, Size, Unit, Capacity, and
    key attributes.
    """
    composed = compose_description_hint(product)
    if composed:
        return composed

    hint = str(product.get("description_hint") or "").strip()
    size = str(product.get("size") or "").strip()
    unit = str(product.get("unit") or "").strip() or "mm"
    sub = str(product.get("sub_category") or "").strip()
    cat = str(product.get("category") or "").strip()
    noun = sub or _section_product_noun(section_text) or cat
    size_phrase = ""
    if size:
        size_phrase = f"{size}{unit}" if unit and unit.lower() not in size.lower() else size
        if "dia" not in (hint or slot_desc).lower() and unit.lower() == "mm":
            size_phrase = f"{size}mm dia"

    weak = (
        (not hint)
        or bool(_SIZE_ONLY_HINT.match(hint))
        or _is_raw_slot_paste(hint, slot_desc)
    )
    if not weak:
        return hint[:500]

    if noun and size_phrase:
        return f"{size_phrase} {noun}".strip()[:500]
    if noun:
        return str(noun).strip()[:500]
    if hint and not _is_raw_slot_paste(hint, slot_desc):
        return hint[:500]
    if size_phrase:
        return size_phrase[:500]
    return (hint or slot_desc or "")[:500]


def _slot_size_hint(slot: dict[str, Any]) -> str | None:
    """Prefer an explicit size_hint, else parse the slot's own description."""
    hint = slot.get("size_hint")
    if not _is_blank_value(hint):
        return str(hint).strip()
    size, _unit = _parse_size_from_text(
        slot.get("description") or slot.get("evidence_text") or ""
    )
    return size


def _apply_slot_evidence_fields(
    products: list[dict[str, Any]],
    *,
    group: dict[str, Any],
    slots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Bind per-slot size/unit/description from BOQ evidence and share parent specs.

    AI sometimes copies the first letter size onto later products, or fills only
    product 0 with shared PN / seat / IS attributes. This pass repairs those
    using the section's authoritative slots + full description.
    """
    if not products:
        return products

    rows = list(slots or group.get("slots") or group.get("qty_rows") or [])
    by_qty_row = {
        str(item.get("qty_row_id") or item.get("row_id") or ""): item
        for item in rows
        if item.get("qty_row_id") or item.get("row_id")
    }
    section_text = str(
        group.get("full_description")
        or group.get("description")
        or ""
    )
    section_pn = _parse_pn_capacity(section_text)

    filled: list[dict[str, Any]] = []
    for index, product in enumerate(products):
        item = dict(product)

        qty_row_id = str(item.get("qty_row_id") or item.get("source_row_id") or "").strip()
        slot = by_qty_row.get(qty_row_id) if qty_row_id else None
        if slot is None and index < len(rows):
            slot = rows[index]

        if slot:
            slot_desc = str(slot.get("description") or "").strip()
            evidence = str(
                slot.get("evidence_text") or slot_desc or section_text
            ).strip()
            size_hint = _slot_size_hint(slot)
            size_from_slot, unit_from_slot = _parse_size_from_text(
                slot_desc or evidence
            )
            if size_hint and not size_from_slot:
                size_from_slot = size_hint
            if size_from_slot:
                current_size = str(item.get("size") or "").strip()
                current_digits = re.sub(r"[^0-9.]", "", current_size)
                hint_digits = re.sub(r"[^0-9.]", "", str(size_from_slot))
                if _is_blank_value(item.get("size")) or (
                    hint_digits and current_digits and hint_digits != current_digits
                ):
                    item["size"] = size_from_slot
                if unit_from_slot and (
                    _is_blank_value(item.get("unit")) or _is_qty_uom(item.get("unit"))
                ):
                    item["unit"] = unit_from_slot

        if section_pn:
            current_cap = str(item.get("capacity") or "").strip()
            current_pn = _parse_pn_capacity(current_cap)
            if _is_blank_value(item.get("capacity")) or (
                current_pn and current_pn != section_pn
            ):
                item["capacity"] = section_pn

        filled.append(normalize_product_fields(item, preserve_class=True))

    filled = _share_section_attributes(filled)
    # Compose AI Description after size/capacity/attrs are final.
    finalized: list[dict[str, Any]] = []
    for index, product in enumerate(filled):
        item = dict(product)
        qty_row_id = str(item.get("qty_row_id") or item.get("source_row_id") or "").strip()
        slot = by_qty_row.get(qty_row_id) if qty_row_id else None
        if slot is None and index < len(rows):
            slot = rows[index]
        slot_desc = str((slot or {}).get("description") or "").strip()
        item["description_hint"] = _enrich_description_hint(
            item,
            section_text=section_text,
            slot_desc=slot_desc,
        )
        finalized.append(item)
    return finalized


def _share_section_attributes(
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copy shared parent attributes onto sibling products that are missing them."""
    if len(products) < 2:
        return products
    shared: dict[str, Any] = {}
    for product in products:
        attrs = coerce_attributes_dict(product.get("attributes"))
        for key, value in attrs.items():
            key_norm = str(key).strip().lower()
            if key_norm not in _SHARED_SECTION_ATTR_KEYS:
                continue
            if _is_blank_value(value):
                continue
            if key_norm not in shared:
                shared[key_norm] = value
    if not shared:
        return products

    updated: list[dict[str, Any]] = []
    for product in products:
        item = dict(product)
        attrs = coerce_attributes_dict(item.get("attributes"))
        changed = False
        for key, value in shared.items():
            # Keep original key casing when already present; else use canonical key.
            existing_key = next(
                (
                    candidate
                    for candidate in attrs
                    if str(candidate).strip().lower() == key
                ),
                key,
            )
            if _is_blank_value(attrs.get(existing_key)):
                attrs[existing_key] = value
                changed = True
        if changed:
            item["attributes"] = attrs
        updated.append(item)
    return updated


def _group_slots(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the authoritative filled Unit/Qty slots for one section."""
    return list(group.get("slots") or group.get("qty_rows") or [])


def _slot_row_id(slot: dict[str, Any]) -> str:
    return str(slot.get("qty_row_id") or slot.get("row_id") or "").strip()


def _missing_product_slots(
    group: dict[str, Any],
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    """Find filled Unit/Qty slots not represented by any extracted product."""
    slots = _group_slots(group)
    if not slots:
        return []
    products = list(row.get("products") or [])
    covered_ids = {
        str(product.get("qty_row_id") or product.get("source_row_id") or "").strip()
        for product in products
        if str(product.get("qty_row_id") or product.get("source_row_id") or "").strip()
    }
    missing: list[dict[str, Any]] = []
    for index, slot in enumerate(slots):
        row_id = _slot_row_id(slot)
        if row_id:
            if row_id not in covered_ids:
                missing.append(slot)
            continue
        # Defensive fallback for malformed legacy slots without row ids.
        if index >= len(products):
            missing.append(slot)
    return missing


def _slot_fallback_product(
    group: dict[str, Any],
    slot: dict[str, Any],
    *,
    product_index: int,
) -> dict[str, Any]:
    """
    Preserve a filled BOQ slot if AI still omits it after the correction pass.

    This does not invent catalog facts. It keeps the slot's BOQ evidence visible
    for expert review and downstream matching instead of silently losing a line.
    """
    evidence = str(
        slot.get("evidence_text")
        or slot.get("description")
        or group.get("full_description")
        or "Product from BOQ Unit/Qty row"
    ).strip()
    row_id = _slot_row_id(slot)
    size_hint = _slot_size_hint(slot)
    size, size_unit = _parse_size_from_text(
        slot.get("description") or evidence
    )
    if size_hint and not size:
        size = size_hint
    capacity = _parse_pn_capacity(
        group.get("full_description") or group.get("description") or evidence
    )
    # Prefer a short synthetic understanding over dumping the raw qty row.
    section_text = str(
        group.get("full_description") or group.get("description") or ""
    )
    noun = _section_product_noun(section_text) or _section_product_noun(evidence)
    size_phrase = ""
    if size:
        unit_label = size_unit or "mm"
        size_phrase = f"{size}mm dia" if str(unit_label).lower() == "mm" else f"{size}{unit_label}"
    if noun and size_phrase:
        hint = f"{size_phrase} {noun}"
    elif noun:
        hint = noun
    elif size_phrase:
        hint = size_phrase
    else:
        hint = str(slot.get("description") or "").strip() or evidence
    product = {
        "product_index": product_index,
        "source_row_id": row_id,
        "qty_row_id": row_id,
        "slot_index": slot.get("slot_index", product_index),
        "slot_id": slot.get("slot_id"),
        "boq_serial": str(slot.get("serial") or "").strip() or None,
        "description_hint": hint[:500],
        "category": None,
        "sub_category": None,
        "class": None,
        "size": size,
        "unit": size_unit,
        "capacity": capacity,
        "make_hint": None,
        "attributes": {},
        "extraction_confidence": 0.0,
        "slot_fallback": True,
        "needs_extraction_review": True,
    }
    return _apply_one_qty(
        normalize_product_fields(product),
        qty=slot.get("qty"),
        unit=slot.get("unit"),
        qty_status=slot.get("qty_status"),
        boq_rate=slot.get("boq_rate"),
    )


def _ensure_minimum_slot_products(
    group: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    """Stabilize to one product per filled Unit/Qty slot (pad missing, trim extras)."""
    slots = list(_group_slots(group))
    updated = dict(row)
    products = list(updated.get("products") or [])

    if slots:
        by_slot: dict[str, list[dict[str, Any]]] = {
            str(slot.get("qty_row_id") or slot.get("row_id") or ""): []
            for slot in slots
            if slot.get("qty_row_id") or slot.get("row_id")
        }
        unbound: list[dict[str, Any]] = []
        for product in products:
            item = dict(product)
            slot_id = str(item.get("qty_row_id") or item.get("source_row_id") or "").strip()
            if slot_id and slot_id in by_slot:
                by_slot[slot_id].append(item)
            else:
                unbound.append(item)

        stabilized: list[dict[str, Any]] = []
        extras_trimmed = 0
        for slot in slots:
            slot_id = str(slot.get("qty_row_id") or slot.get("row_id") or "").strip()
            if not slot_id:
                continue
            candidates = list(by_slot.get(slot_id) or [])
            if not candidates and unbound:
                candidates = [unbound.pop(0)]
            if not candidates:
                stabilized.append(
                    _slot_fallback_product(
                        group,
                        slot,
                        product_index=len(stabilized),
                    )
                )
                continue
            # One product per slot — keep the strongest qty/evidence rank.
            candidates.sort(key=_qty_rank, reverse=True)
            chosen = dict(candidates[0])
            chosen["qty_row_id"] = slot_id
            chosen["source_row_id"] = slot_id
            chosen["slot_index"] = int(slot.get("slot_index") or len(stabilized))
            chosen["product_index"] = len(stabilized)
            stabilized.append(chosen)
            extras_trimmed += max(0, len(candidates) - 1)

        extras_trimmed += len(unbound)
        if extras_trimmed:
            logger.warning(
                "Trimmed %s extra AI product(s) for row=%s to match %s Unit/Qty slot(s)",
                extras_trimmed,
                group.get("row_id"),
                len(slots),
            )
            updated["slot_extra_products_trimmed"] = extras_trimmed

        products = stabilized
        missing_slots: list[dict[str, Any]] = []
    else:
        missing_slots = _missing_product_slots(group, {"products": products})
        for slot in missing_slots:
            products.append(
                _slot_fallback_product(
                    group,
                    slot,
                    product_index=len(products),
                )
            )

    for index, item in enumerate(products):
        item["product_index"] = index

    updated["products"] = _apply_slot_evidence_fields(
        products,
        group=group,
        slots=slots,
    )
    updated["skip_matching"] = False
    if missing_slots:
        updated["slot_shortfall_fallback_count"] = len(missing_slots)
    elif slots and any(p.get("slot_fallback") for p in updated["products"]):
        updated["slot_shortfall_fallback_count"] = sum(
            1 for p in updated["products"] if p.get("slot_fallback")
        )
    updated.pop("skip_reason", None)
    if missing_slots:
        logger.warning(
            "AI extraction still missed %s Unit/Qty slot(s) for row=%s; "
            "added BOQ-evidence review products",
            len(missing_slots),
            group.get("row_id"),
        )
    return updated
