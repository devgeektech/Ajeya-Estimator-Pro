"""AI extraction of multiple products per grouped BOQ anchor row."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ai.context import build_database_context, load_rate_master_taxonomy, snap_product_taxonomy
from ai.service import AIService
from common.exceptions import AIServiceError
from utils.attribute_parser import coerce_attributes_dict
from utils.product_synonyms import display_material_label

from apps.boq.services.boq_row_grouping_service import (
    anchor_qty_unit,
    grouped_anchor_rows,
    resolve_anchor_row_id,
    has_quantity,
)
from apps.boq.services.serial_normalizer import analysis_fields, letter_from_serial

logger = logging.getLogger("boq_ai")

_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_MAX_BATCH_CHARS = 14000
_MINIMUM_SLOT_RETRY_INSTRUCTION = """

CORRECTION — slot coverage required:
- Return ≥ slot_count products; every slots[].qty_row_id must appear on a product.
- Per-product size/description_hint from that slot only; shared PN/seat/IS on all.
- Return the full corrected rows JSON.
"""

# Nominal size from letter/qty row text: "200mm dia", "a) 150 mm", "80 NB".
_SIZE_FROM_TEXT = re.compile(
    r"(?i)(?:^|[^0-9])(\d+(?:\.\d+)?)\s*(mm|nb|inch|in|cm)?\b"
)
_PN_RATING_FROM_TEXT = re.compile(r"(?i)\bPN\s*[- ]?\s*(\d+)\b")
_PLACEHOLDER_CLASS_VALUES = frozenset(
    {"0", "00", "-", "--", "n/a", "na", "none", "null", "nil"}
)
# Section-level attributes copied onto every slot product when missing.
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

def _extract_batch_size() -> int:
    from django.conf import settings

    return max(1, int(getattr(settings, "AI_ROW_EXTRACTION_BATCH_SIZE", 5) or 5))


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

# Spec labels only: "Speed", "Speed (rpm)", "Pressure: 10 bar" — not "Pressure switch".
_SPEC_LABEL_ONLY = re.compile(
    r"^(?P<label>speed|capacity|head|pressure|flow|power|voltage|rpm|efficiency|"
    r"dimension|size|weight|model|type)"
    r"(?:\s*\([^)]*\))?"
    r"(?:\s*:.*)?$",
    re.IGNORECASE,
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


def _lineage_has_quantity(rows: list[dict[str, Any]], lineage_ids: list[str]) -> bool:
    index = {str(row.get("row_id")): row for row in rows if row.get("row_id")}
    for row_id in lineage_ids:
        row = index.get(str(row_id))
        if row and has_quantity(analysis_fields(row)):
            return True
    return False


def should_skip_anchor_group(group: dict[str, Any], *, lineage_has_qty: bool) -> bool:
    """Skip section-style / title-only anchor groups before calling AI."""
    full_text = str(group.get("full_description") or "").strip()
    if not full_text:
        return True

    # Lineage sections with any filled qty/unit (including 0 / Rate Only) stay actionable.
    if group.get("qty_status") and group.get("qty_status") != "empty":
        return False
    if group.get("qty_rows"):
        return False

    anchor_fields = group.get("anchor_fields") or {}
    if has_quantity(anchor_fields) or lineage_has_qty:
        return False

    serial = str(group.get("serial") or "").strip()
    # Dotted packages (1.1, 2.15) may still hold lettered products without qty on the root.
    if re.match(r"^(\d+(?:\.\d+)+)$", serial):
        return False
    # Lettered product lines without qty still need extraction.
    if letter_from_serial(serial):
        return False

    # Bare chapter titles (1, 2, 3) or depth-0 leftovers after hybrid split — skip.
    if re.match(r"^\d+$", serial) or int(group.get("depth") or 0) == 0:
        return True

    return False


def _iter_extract_batches(groups: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Pack groups into AI batches by count and approximate payload size."""
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for group in groups:
        payload = _compact_anchor_payload(group)
        size = len(json.dumps(payload, ensure_ascii=False))
        would_overflow = (
            current
            and (
                len(current) >= _extract_batch_size()
                or current_chars + size > _MAX_BATCH_CHARS
            )
        )
        if would_overflow:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(group)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _apply_one_qty(
    item: dict[str, Any],
    *,
    qty: Any,
    unit: Any,
    qty_status: str | None = None,
    boq_rate: Any = None,
) -> dict[str, Any]:
    """Fill one product from one BOQ qty row; never overwrite product unit."""
    row_unit = None if _is_blank_value(unit) else str(unit).strip()
    status = qty_status or ("empty" if qty in (None, "") else "numeric")
    if row_unit and _is_blank_value(item.get("quantity_unit")):
        item["quantity_unit"] = row_unit
    if status == "rate_only":
        item["rate_only"] = True
        if _is_blank_value(item.get("quantity")):
            item["quantity"] = "Rate Only"
        if boq_rate not in (None, "") and _is_blank_value(item.get("boq_rate")):
            item["boq_rate"] = boq_rate
    elif status == "zero":
        item["rate_only"] = False
        item["quantity"] = 0
    elif status == "numeric" or qty not in (None, ""):
        item["rate_only"] = False
        if _is_blank_value(item.get("quantity")):
            item["quantity"] = qty
    return item


def quantity_display_fields(product: dict[str, Any]) -> dict[str, Any]:
    """Shared Analysis / Make & Vendor / Labour / Review quantity display fields."""
    quantity = product.get("quantity")
    quantity_unit = product.get("quantity_unit")
    has_quantity = quantity not in (None, "")
    return {
        "quantity": quantity,
        "quantity_unit": quantity_unit or "",
        "quantity_display": str(quantity) if has_quantity else "—",
        "quantity_unit_display": (
            str(quantity_unit).strip() if quantity_unit not in (None, "") else "—"
        ),
        "show_quantity": has_quantity or bool(str(quantity_unit or "").strip()),
        "rate_only": bool(product.get("rate_only")),
    }


def rehydrate_products_quantity_from_group(
    products: list[dict[str, Any]],
    group: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """
    Fill blank product ``quantity`` / ``quantity_unit`` from BOQ Unit/Qty slots.

    Safe to call repeatedly: only blank quantity fields are filled. Used when
    products kept ``qty_row_id`` but lost quantity after mapping/rematch.
    """
    if not products or not group:
        return list(products or [])
    return _apply_row_qty_unit(
        list(products),
        qty=group.get("qty", group.get("anchor_qty")),
        unit=group.get("unit", group.get("anchor_unit")),
        qty_status=group.get("qty_status"),
        boq_rate=group.get("boq_rate"),
        qty_rows=list(group.get("qty_rows") or []),
        slots=list(group.get("slots") or group.get("qty_rows") or []),
    )


def rehydrate_analysis_rows_quantity(
    boq_data: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Re-bind every analysis row's products to their BOQ Unit/Qty slots."""
    group_by_row = {
        str(group.get("row_id") or ""): group
        for group in grouped_anchor_rows(boq_data or {})
        if group.get("row_id")
    }
    updated: list[dict[str, Any]] = []
    for row in rows or []:
        row_id = str(row.get("row_id") or "")
        products = list(row.get("products") or [])
        if not products:
            updated.append(row)
            continue
        filled = rehydrate_products_quantity_from_group(
            products,
            group_by_row.get(row_id),
        )
        updated.append({**row, "products": filled})
    return updated


def _apply_row_qty_unit(
    products: list[dict[str, Any]],
    *,
    qty: Any,
    unit: Any,
    qty_status: str | None = None,
    boq_rate: Any = None,
    qty_rows: list[dict[str, Any]] | None = None,
    slots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Fill quantity / quantity_unit from BOQ qty slots.

    One Unit/Qty row = one product slot. Prefer binding by ``source_row_id`` /
    ``qty_row_id`` when present; otherwise zip products to slots in order.
    Persist ``slot_index`` / ``qty_row_id`` so Make & Vendor → Labour → Review
    keep the same priced line identity.
    """
    if not products:
        return products

    rows = list(slots or qty_rows or [])
    if len(rows) > 1:
        by_qty_row = {
            str(item.get("qty_row_id") or item.get("row_id") or ""): item
            for item in rows
            if item.get("qty_row_id") or item.get("row_id")
        }
        used_slot_ids: set[str] = set()
        filled: list[dict[str, Any]] = []
        for index, product in enumerate(products):
            item = _normalize_product_fields(product)
            qty_row = None
            source_id = str(item.get("source_row_id") or item.get("qty_row_id") or "")
            if source_id and source_id in by_qty_row:
                qty_row = by_qty_row[source_id]
            elif index < len(rows):
                qty_row = rows[index]
            if qty_row:
                item = _apply_one_qty(
                    item,
                    qty=qty_row.get("qty"),
                    unit=qty_row.get("unit"),
                    qty_status=qty_row.get("qty_status"),
                    boq_rate=qty_row.get("boq_rate"),
                )
                slot_row_id = str(qty_row.get("qty_row_id") or qty_row.get("row_id") or "")
                if slot_row_id and _is_blank_value(item.get("source_row_id")):
                    item["source_row_id"] = slot_row_id
                item["qty_row_id"] = slot_row_id or item.get("qty_row_id")
                item["slot_index"] = qty_row.get("slot_index", index)
                item["slot_id"] = qty_row.get("slot_id") or item.get("slot_id")
                slot_serial = str(qty_row.get("serial") or "").strip()
                if slot_serial:
                    item["boq_serial"] = slot_serial
                used_slot_ids.add(slot_row_id)
            filled.append(item)
        return filled

    if len(rows) == 1:
        only = rows[0]
        qty = only.get("qty", qty)
        unit = only.get("unit", unit)
        qty_status = only.get("qty_status", qty_status)
        boq_rate = only.get("boq_rate", boq_rate)
        slot_row_id = str(only.get("qty_row_id") or only.get("row_id") or "")
        slot_serial = str(only.get("serial") or "").strip()
        return [
            {
                **_apply_one_qty(
                    _normalize_product_fields(product),
                    qty=qty,
                    unit=unit,
                    qty_status=qty_status,
                    boq_rate=boq_rate,
                ),
                "qty_row_id": slot_row_id or product.get("qty_row_id"),
                "slot_index": only.get("slot_index", 0),
                "slot_id": only.get("slot_id"),
                "source_row_id": product.get("source_row_id") or slot_row_id,
                **({"boq_serial": slot_serial} if slot_serial else {}),
            }
            for product in products
        ]

    return [
        _apply_one_qty(
            _normalize_product_fields(product),
            qty=qty,
            unit=unit,
            qty_status=qty_status,
            boq_rate=boq_rate,
        )
        for product in products
    ]


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
        product = _normalize_product_fields(product)
        cleaned.append(snap_product_taxonomy(product, taxonomy))
    return cleaned


def _is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _is_placeholder_class(value: Any) -> bool:
    if _is_blank_value(value):
        return True
    return str(value).strip().casefold() in _PLACEHOLDER_CLASS_VALUES


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


_SIZE_ONLY_HINT = re.compile(
    r"(?i)^\s*(?:[a-z]\)?\s*)?\d+(?:\.\d+)?\s*(?:mm|nb|inch|in|cm)?\s*(?:dia(?:meter)?)?\s*$"
)


def _section_product_noun(section_text: str) -> str:
    """Pull a short product noun from parent BOQ text for weak size-only hints."""
    blob = str(section_text or "").strip()
    if not blob:
        return ""
    patterns = (
        r"(?i)\b(sluice\s+valve|butterfly\s+valve|ball\s+valve|gate\s+valve|"
        r"non[\s-]?return\s+valve|check\s+valve|y[\s-]?strainer|strainer|"
        r"hydrant|landing\s+valve|hose\s+reel|sprinkler|fire\s+pump|jockey\s+pump|"
        r"pressure\s+switch|flow\s+switch|ms\s+pipe|gi\s+pipe|pipework|pipe)\b"
    )
    match = re.search(patterns, blob)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def _enrich_description_hint(
    product: dict[str, Any],
    *,
    section_text: str,
    slot_desc: str,
) -> str:
    """Ensure description_hint carries product type + size for better DB recall."""
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

    weak = (not hint) or bool(_SIZE_ONLY_HINT.match(hint))
    if weak and noun and size_phrase:
        return f"{size_phrase} {noun}".strip()[:500]
    if weak and noun:
        base = slot_desc or hint or noun
        if noun.lower() not in base.lower():
            return f"{base} {noun}".strip()[:500]
        return base[:500]
    if hint and noun and noun.lower() not in hint.lower() and _SIZE_ONLY_HINT.match(hint):
        return f"{hint} {noun}".strip()[:500]
    return hint[:500] if hint else (slot_desc or "")[:500]


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
        if _is_placeholder_class(item.get("class")):
            item["class"] = None

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
            item["description_hint"] = _enrich_description_hint(
                item,
                section_text=section_text,
                slot_desc=slot_desc if slot else "",
            )

        if section_pn:
            current_cap = str(item.get("capacity") or "").strip()
            current_pn = _parse_pn_capacity(current_cap)
            if _is_blank_value(item.get("capacity")) or (
                current_pn and current_pn != section_pn
            ):
                item["capacity"] = section_pn

        filled.append(_normalize_product_fields(item))

    return _share_section_attributes(filled)


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


# BOQ quantity UOMs — must never populate product ``unit`` (Rate_Master measurement).
_QTY_UOM_TOKENS = frozenset(
    {
        "each",
        "ea",
        "nos",
        "no",
        "no.",
        "nr",
        "set",
        "sets",
        "lot",
        "ls",
        "lumpsum",
        "lump sum",
        "rm",
        "r.m",
        "r.mt",
        "mtr",
        "mtrs",
        "meter",
        "meters",
        "metre",
        "metres",
        "sqm",
        "sq.m",
        "cum",
        "cu.m",
    }
)

# Trailing measurement unit on size text (e.g. "63mm", "2 inch") → Rate_Master Unit.
_SIZE_MEASUREMENT_UNIT = re.compile(
    r"(?i)^\s*.*?\s*(mm|cm|nb|inch|in)\s*$"
)


def _is_qty_uom(value: Any) -> bool:
    if _is_blank_value(value):
        return False
    return str(value).strip().lower() in _QTY_UOM_TOKENS


def _measurement_unit_from_size(size: Any) -> str | None:
    if _is_blank_value(size):
        return None
    match = _SIZE_MEASUREMENT_UNIT.match(str(size).strip())
    if not match:
        return None
    token = match.group(1).lower()
    if token == "in":
        return "inch"
    if token == "nb":
        return "NB"
    return token


def _normalize_product_unit_fields(product: dict[str, Any]) -> dict[str, Any]:
    """
    Keep ``unit`` as Rate_Master measurement (mm/cm/NB/…) and BOQ UOM on
    ``quantity_unit`` only.
    """
    item = dict(product)
    raw_unit = item.get("unit")
    if _is_qty_uom(raw_unit):
        if _is_blank_value(item.get("quantity_unit")):
            item["quantity_unit"] = str(raw_unit).strip()
        item["unit"] = None

    if _is_blank_value(item.get("unit")):
        derived = _measurement_unit_from_size(item.get("size"))
        if derived:
            item["unit"] = derived
    return item


# Material / construction phrases → Rate_Master Class tokens.
_MATERIAL_ATTR_KEYS = frozenset(
    {"material", "body_material", "construction", "material_of_construction", "moc"}
)


def _normalize_class_material(value: Any) -> str | None:
    if _is_blank_value(value):
        return None
    return display_material_label(value) or None


def _promote_material_to_class(product: dict[str, Any]) -> dict[str, Any]:
    """
    Fill blank class from material attributes when useful.

    Keep material keys on attributes so Rate_Master rows that store Class=0 and
    material in Attribute still overlap during matching.
    """
    item = dict(product)
    attrs = coerce_attributes_dict(item.get("attributes"))
    material_value = None
    for key, value in attrs.items():
        if str(key).strip().lower() in _MATERIAL_ATTR_KEYS and not _is_blank_value(value):
            material_value = value
            break

    sub_norm = re.sub(r"[^0-9a-zA-Z]+", " ", str(item.get("sub_category") or "").lower())
    sub_norm = re.sub(r"\s+", " ", sub_norm).strip()
    if material_value is not None:
        material_norm = re.sub(r"[^0-9a-zA-Z]+", " ", str(material_value).lower())
        material_norm = re.sub(r"\s+", " ", material_norm).strip()
        if sub_norm and material_norm == sub_norm:
            material_value = None

    if _is_blank_value(item.get("class")) and material_value is not None:
        item["class"] = _normalize_class_material(material_value)
    elif not _is_blank_value(item.get("class")):
        item["class"] = _normalize_class_material(item.get("class"))

    item["attributes"] = attrs
    return item


def _normalize_product_fields(product: dict[str, Any]) -> dict[str, Any]:
    """Normalize unit/qty UOM and promote material into class."""
    item = _normalize_product_unit_fields(_promote_material_to_class(product))
    if _is_placeholder_class(item.get("class")):
        item["class"] = None
    return item


def _consolidate_to_anchors(
    anchor_groups: list[dict[str, Any]],
    extracted_by_id: dict[str, dict[str, Any]],
) -> None:
    """Move products returned on group child row_ids onto the anchor row."""
    anchor_ids = {str(g.get("row_id")) for g in anchor_groups if g.get("row_id")}

    for group in anchor_groups:
        anchor_id = str(group.get("row_id") or "")
        if not anchor_id:
            continue
        # Own products only — do not pull from shared ancestors/siblings.
        group_ids = [str(row_id) for row_id in (group.get("group_ids") or [anchor_id])]

        merged_products: list[dict[str, Any]] = []
        for row_id in group_ids:
            row = extracted_by_id.get(row_id) or {}
            merged_products.extend(row.get("products") or [])

        if not merged_products:
            continue

        existing = extracted_by_id.get(anchor_id) or {}
        taxonomy = load_rate_master_taxonomy()
        anchor_row: dict[str, Any] = {
            **existing,
            "row_id": anchor_id,
            "products": _filter_spec_products(merged_products, taxonomy=taxonomy),
            "activities": [],
            "skip_matching": not bool(merged_products),
        }
        anchor_row.pop("skip_reason", None)
        extracted_by_id[anchor_id] = anchor_row

        for row_id in group_ids:
            if row_id == anchor_id:
                continue
            if row_id in anchor_ids:
                continue
            extracted_by_id[row_id] = {
                "row_id": row_id,
                "skip_matching": True,
                "products": [],
                "activities": [],
                "skip_reason": "lineage_child_row",
            }


def _resolve_batch_row(
    group: dict[str, Any],
    by_id: dict[Any, dict[str, Any]],
) -> dict[str, Any]:
    anchor_id = group.get("row_id")
    row = by_id.get(anchor_id)
    if row is not None:
        return row

    # Prefer group children only — never shared ancestors (prevents sibling theft).
    for row_id in group.get("group_ids") or []:
        if str(row_id) == str(anchor_id):
            continue
        candidate = by_id.get(row_id)
        if candidate is not None:
            return candidate

    return {
        "row_id": anchor_id,
        "skip_matching": True,
        "products": [],
        "activities": [],
        "skip_reason": "ai_missing_row",
    }


def _build_anchor_groups(boq_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = boq_data.get("rows") or []
    index = {str(row.get("row_id")): row for row in rows if row.get("row_id")}
    groups: list[dict[str, Any]] = []

    for group in grouped_anchor_rows(boq_data):
        row_id = str(group.get("row_id") or "")
        anchor_row = index.get(row_id) or {}
        lineage_ids = list(group.get("lineage_ids") or [row_id])
        qty_rows = list(group.get("qty_rows") or [])
        qty = group.get("qty")
        unit = group.get("unit")
        if not qty_rows and qty in (None, "") and unit in (None, ""):
            qty, unit = anchor_qty_unit(index, row_id)
        groups.append(
            {
                **group,
                "anchor_fields": analysis_fields(anchor_row),
                "lineage_has_qty": bool(qty_rows) or _lineage_has_quantity(rows, lineage_ids),
                "anchor_qty": qty,
                "anchor_unit": unit,
                "qty_status": group.get("qty_status") or ("empty" if not qty_rows else "numeric"),
                "boq_rate": group.get("boq_rate"),
                "qty_rows": qty_rows,
            }
        )
    return groups


def _compact_anchor_payload(group: dict[str, Any]) -> dict[str, Any]:
    """Compact section payload for extract — slots carry qty/size; skip duplicate qty_rows."""
    slots = []
    for slot in group.get("slots") or []:
        slots.append(
            {
                "slot_index": slot.get("slot_index"),
                "qty_row_id": slot.get("qty_row_id"),
                "serial": slot.get("serial"),
                "description": slot.get("description"),
                "size_hint": slot.get("size_hint"),
                "qty": slot.get("qty"),
                "unit": slot.get("unit"),
                "qty_status": slot.get("qty_status"),
                "rate_only": bool(slot.get("rate_only")),
                "boq_rate": slot.get("boq_rate"),
                "evidence_text": slot.get("evidence_text"),
            }
        )
    lineage = group.get("lineage_parts") or []
    # Keep lineage short — full text already lives in description.
    if len(lineage) > 8:
        lineage = lineage[:3] + lineage[-5:]
    return {
        "row_id": group.get("row_id"),
        "serial": group.get("serial"),
        "description": group.get("full_description"),
        "lineage_lines": lineage,
        "slot_count": int(group.get("slot_count") or len(slots)),
        "slots": slots,
        "heuristic_skip": should_skip_anchor_group(
            group,
            lineage_has_qty=bool(group.get("lineage_has_qty")),
        ),
    }


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
        _normalize_product_fields(product),
        qty=slot.get("qty"),
        unit=slot.get("unit"),
        qty_status=slot.get("qty_status"),
        boq_rate=slot.get("boq_rate"),
    )


def _ensure_minimum_slot_products(
    group: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    """Guarantee one visible product per filled Unit/Qty slot."""
    missing_slots = _missing_product_slots(group, row)
    if not missing_slots:
        return row
    updated = dict(row)
    products = list(updated.get("products") or [])
    for slot in missing_slots:
        products.append(
            _slot_fallback_product(
                group,
                slot,
                product_index=len(products),
            )
        )
    updated["products"] = _apply_slot_evidence_fields(
        products,
        group=group,
        slots=_group_slots(group),
    )
    updated["skip_matching"] = False
    updated["slot_shortfall_fallback_count"] = len(missing_slots)
    updated.pop("skip_reason", None)
    logger.warning(
        "AI extraction still missed %s Unit/Qty slot(s) for row=%s; "
        "added BOQ-evidence review products",
        len(missing_slots),
        group.get("row_id"),
    )
    return updated


class BOQExtractionService:
    """Extract products from grouped BOQ anchor rows via OpenAI."""

    def __init__(self, boq_data: dict):
        self.boq_data = boq_data or {}
        self.ai = AIService()
        self._database_context: str | None = None
        self._taxonomy: dict[str, Any] | None = None

    def _database_context_text(self) -> str:
        if self._database_context is None:
            self._database_context = build_database_context()
        return self._database_context

    def _rate_master_taxonomy(self) -> dict[str, Any]:
        if self._taxonomy is None:
            self._taxonomy = load_rate_master_taxonomy()
        return self._taxonomy

    def extract(self, progress_callback=None) -> dict[str, Any]:
        if not self.ai.is_enabled():
            raise AIServiceError("OPENAI_API_KEY is not configured.")

        # Build once for the whole extract job (not once per AI batch).
        context_text = self._database_context_text()
        self._rate_master_taxonomy()
        logger.info(
            "BOQ extract AI database context ready chars=%s",
            len(context_text),
        )
        logger.info("BOQ extract AI database context payload=%s", context_text)

        flat_rows = self.boq_data.get("rows") or []
        anchor_groups = _build_anchor_groups(self.boq_data)
        actionable_groups = [
            group
            for group in anchor_groups
            if not should_skip_anchor_group(
                group,
                lineage_has_qty=bool(group.get("lineage_has_qty")),
            )
        ]

        extracted_by_id: dict[str, dict[str, Any]] = {}
        batches = _iter_extract_batches(actionable_groups)
        extract_total = max(len(actionable_groups), 1)
        done = 0
        # Report 0/total immediately so the UI does not sit on a fake mid-band %.
        if progress_callback:
            progress_callback(0, extract_total)
        for batch in batches:
            for row in self._extract_batch(batch):
                row_id = row.get("row_id")
                if row_id:
                    extracted_by_id[str(row_id)] = row
            done += len(batch)
            if progress_callback:
                progress_callback(done, extract_total)

        _consolidate_to_anchors(anchor_groups, extracted_by_id)

        block_by_anchor = {
            str(group.get("row_id")): group
            for group in anchor_groups
            if group.get("row_id")
        }
        block_member_ids: set[str] = set()
        for group in anchor_groups:
            for member_id in group.get("group_ids") or []:
                block_member_ids.add(str(member_id))

        extracted_rows: list[dict[str, Any]] = []
        for row in flat_rows:
            row_id = row.get("row_id")
            if not row_id:
                continue
            row_key = str(row_id)

            group = block_by_anchor.get(row_key)
            if group is not None:
                if should_skip_anchor_group(
                    group,
                    lineage_has_qty=bool(group.get("lineage_has_qty")),
                ):
                    extracted_rows.append(
                        {
                            "row_id": row_id,
                            "skip_matching": True,
                            "products": [],
                            "activities": [],
                            "skip_reason": "section_or_empty_row",
                        }
                    )
                    continue

                extracted_rows.append(
                    extracted_by_id.get(
                        row_key,
                        {
                            "row_id": row_id,
                            "skip_matching": True,
                            "products": [],
                            "activities": [],
                            "skip_reason": "ai_missing_row",
                        },
                    )
                )
                continue

            if row_key in block_member_ids:
                extracted_rows.append(
                    {
                        "row_id": row_id,
                        "skip_matching": True,
                        "products": [],
                        "activities": [],
                        "skip_reason": "lineage_child_row",
                    }
                )
                continue

            # Rows outside any filled Unit/Qty block (headers, blanks, totals).
            extracted_rows.append(
                {
                    "row_id": row_id,
                    "skip_matching": True,
                    "products": [],
                    "activities": [],
                    "skip_reason": "section_or_empty_row",
                }
            )

        return {
            "schema_version": 1,
            "row_count": len(flat_rows),
            "extracted_row_count": len(extracted_rows),
            "rows": extracted_rows,
        }

    def extract_anchor(self, row_id: str) -> dict[str, Any]:
        """Extract products for one anchor group (and its lineage stubs)."""
        if not self.ai.is_enabled():
            raise AIServiceError("OPENAI_API_KEY is not configured.")

        flat_rows = self.boq_data.get("rows") or []
        if not any(str(row.get("row_id")) == str(row_id) for row in flat_rows):
            raise AIServiceError(f"Unknown BOQ row: {row_id}")

        anchor_id = resolve_anchor_row_id(self.boq_data, str(row_id))
        groups = _build_anchor_groups(self.boq_data)
        group = next((item for item in groups if str(item.get("row_id")) == anchor_id), None)
        if group is None:
            raise AIServiceError(f"Unknown BOQ anchor row: {anchor_id}")

        lineage_ids = [str(item) for item in (group.get("lineage_ids") or [anchor_id])]
        group_ids = [str(item) for item in (group.get("group_ids") or [anchor_id])]
        if should_skip_anchor_group(group, lineage_has_qty=bool(group.get("lineage_has_qty"))):
            rows = [
                {
                    "row_id": anchor_id,
                    "skip_matching": True,
                    "products": [],
                    "activities": [],
                    "skip_reason": "section_or_empty_row",
                },
                *[
                    {
                        "row_id": child_id,
                        "skip_matching": True,
                        "products": [],
                        "activities": [],
                        "skip_reason": "lineage_child_row",
                    }
                    for child_id in group_ids[1:]
                ],
            ]
            return {
                "schema_version": 1,
                "anchor_row_id": anchor_id,
                "lineage_ids": lineage_ids,
                "rows": rows,
            }

        extracted_by_id: dict[str, dict[str, Any]] = {}
        for row in self._extract_batch([group]):
            extracted_row_id = row.get("row_id")
            if extracted_row_id:
                extracted_by_id[str(extracted_row_id)] = row
        _consolidate_to_anchors([group], extracted_by_id)

        rows = []
        for group_id in group_ids:
            if group_id == anchor_id:
                rows.append(
                    extracted_by_id.get(
                        anchor_id,
                        {
                            "row_id": anchor_id,
                            "skip_matching": True,
                            "products": [],
                            "activities": [],
                            "skip_reason": "ai_missing_row",
                        },
                    )
                )
            else:
                rows.append(
                    {
                        "row_id": group_id,
                        "skip_matching": True,
                        "products": [],
                        "activities": [],
                        "skip_reason": "lineage_child_row",
                    }
                )
        return {
            "schema_version": 1,
            "anchor_row_id": anchor_id,
            "lineage_ids": lineage_ids,
            "rows": rows,
        }

    def _extract_batch(self, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Extract a batch, retry under-covered sections once, then preserve every slot.

        AI may return extra evidenced products. Those are never truncated. A second,
        focused pass is only used when a filled Unit/Qty slot has no product.
        """
        normalized = self._extract_batch_once(groups)
        row_by_id = {
            str(row.get("row_id")): row
            for row in normalized
            if row.get("row_id") is not None
        }
        underfilled = [
            group
            for group in groups
            if _missing_product_slots(
                group,
                row_by_id.get(str(group.get("row_id"))) or {},
            )
        ]
        if underfilled:
            logger.warning(
                "Retrying AI extraction for %s section(s) missing Unit/Qty slot products",
                len(underfilled),
            )
            try:
                repaired_rows = self._extract_batch_once(
                    underfilled,
                    minimum_slot_retry=True,
                )
            except Exception:
                logger.exception(
                    "Minimum-slot extraction retry failed; preserving BOQ slots for review"
                )
                repaired_rows = []
            repaired_by_id = {
                str(row.get("row_id")): row
                for row in repaired_rows
                if row.get("row_id") is not None
            }
            for group in underfilled:
                row_id = str(group.get("row_id"))
                current = row_by_id.get(row_id) or {}
                repaired = repaired_by_id.get(row_id)
                if repaired is None:
                    continue
                current_missing = len(_missing_product_slots(group, current))
                repaired_missing = len(_missing_product_slots(group, repaired))
                if repaired_missing < current_missing or (
                    repaired_missing == current_missing
                    and len(repaired.get("products") or [])
                    > len(current.get("products") or [])
                ):
                    row_by_id[row_id] = repaired

        return [
            _ensure_minimum_slot_products(
                group,
                row_by_id.get(str(group.get("row_id"))) or {
                    "row_id": group.get("row_id"),
                    "products": [],
                },
            )
            for group in groups
        ]

    def _extract_batch_once(
        self,
        groups: list[dict[str, Any]],
        *,
        minimum_slot_retry: bool = False,
    ) -> list[dict[str, Any]]:
        template = AIService.load_prompt("extract_products.txt")
        payload = [_compact_anchor_payload(group) for group in groups]
        prompt = (
            template.replace("{{DATABASE_CONTEXT}}", self._database_context_text())
            .replace("{{ROWS_PAYLOAD}}", json.dumps(payload, ensure_ascii=False, default=str))
        )
        if minimum_slot_retry:
            prompt += _MINIMUM_SLOT_RETRY_INSTRUCTION
        response = self.ai.complete_json(prompt, template_name="extract_products.txt")
        rows = response.get("rows") or []
        if not isinstance(rows, list):
            raise AIServiceError("Extraction response missing rows list.")

        by_id = {row.get("row_id"): row for row in rows if row.get("row_id")}
        taxonomy = self._rate_master_taxonomy()
        normalized: list[dict[str, Any]] = []
        for group in groups:
            row_id = group.get("row_id")
            row = dict(_resolve_batch_row(group, by_id))
            # Batch output is one normalized row per requested anchor even when
            # the model accidentally returns a child row id.
            row["row_id"] = row_id
            products = _filter_spec_products(
                list(row.get("products") or []),
                taxonomy=taxonomy,
            )
            row["products"] = _apply_slot_evidence_fields(
                _apply_row_qty_unit(
                    products,
                    qty=group.get("anchor_qty"),
                    unit=group.get("anchor_unit"),
                    qty_status=group.get("qty_status"),
                    boq_rate=group.get("boq_rate"),
                    qty_rows=list(group.get("qty_rows") or []),
                    slots=list(group.get("slots") or []),
                ),
                group=group,
                slots=list(group.get("slots") or []),
            )
            row["activities"] = []
            row.setdefault("skip_matching", not row.get("products"))
            normalized.append(row)
        return normalized
