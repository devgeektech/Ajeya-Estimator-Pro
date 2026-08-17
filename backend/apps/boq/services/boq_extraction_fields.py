"""Product field normalization and quantity display helpers for BOQ extraction."""
from __future__ import annotations

import re
from typing import Any

from ai.context import is_catalog_class, snap_product_taxonomy
from apps.boq.services.boq_row_fields import is_blank as _is_blank_value
from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows
from utils.attribute_parser import coerce_attributes_dict
from utils.product_synonyms import display_material_label


_PLACEHOLDER_CLASS_VALUES = frozenset(
    {"-", "--", "n/a", "na", "none", "null", "nil"}
)


def _slot_order_key(product: dict[str, Any]) -> tuple[int, int]:
    try:
        slot = int(product["slot_index"]) if product.get("slot_index") not in (None, "") else 10**9
    except (TypeError, ValueError):
        slot = 10**9
    try:
        index = int(product.get("product_index") or 0)
    except (TypeError, ValueError):
        index = 0
    return (slot, index)


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


_SIZE_MEASUREMENT_UNIT = re.compile(
    r"(?i)^\s*.*?\s*(mm|cm|nb|inch|in)\s*$"
)


_MATERIAL_ATTR_KEYS = frozenset(
    {"material", "body_material", "construction", "material_of_construction", "moc"}
)


def _is_placeholder_class(value: Any) -> bool:
    if _is_blank_value(value):
        return True
    return str(value).strip().casefold() in _PLACEHOLDER_CLASS_VALUES


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


def _normalize_class_material(value: Any) -> str | None:
    if _is_blank_value(value):
        return None
    return display_material_label(value) or None


def _material_is_catalog_class(product: dict[str, Any], value: Any) -> bool:
    return is_catalog_class(
        value,
        category=product.get("category"),
        sub_category=product.get("sub_category"),
    )


def _promote_material_to_class(
    product: dict[str, Any],
    *,
    preserve_class: bool = False,
) -> dict[str, Any]:
    """
    Fill blank class from material attributes when useful.

    Keep material keys on attributes so Rate_Master rows that store Class=0 and
    material in Attribute still overlap during matching. Never replace an
    expert-entered class (including ``0``) with a material token.
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

    class_value = item.get("class")
    class_is_empty = _is_blank_value(class_value) or (
        not preserve_class and _is_placeholder_class(class_value)
    )
    if class_is_empty and material_value is not None:
        # Only copy material into Class when that token is a Rate_Master Class
        # for this category / sub-category (not for valves where Class is ``0``).
        material_class = _normalize_class_material(material_value)
        if material_class and _material_is_catalog_class(item, material_class):
            item["class"] = material_class
    elif not class_is_empty and _material_is_catalog_class(item, class_value):
        item["class"] = _normalize_class_material(class_value) or class_value

    item["attributes"] = attrs
    return item


def normalize_product_fields(
    product: dict[str, Any],
    *,
    preserve_class: bool = False,
) -> dict[str, Any]:
    """Normalize unit/qty UOM and optionally promote material into class."""
    item = _normalize_product_unit_fields(
        _promote_material_to_class(product, preserve_class=preserve_class)
    )
    # Extract-only: AI often dumps Class=0. Expert edit / rematch must keep ``0``.
    if not preserve_class and _is_placeholder_class(item.get("class")):
        item["class"] = None
    return item


# Backward-compatible private alias (prefer normalize_product_fields).
_normalize_product_fields = normalize_product_fields


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
            item = normalize_product_fields(product, preserve_class=True)
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
        filled.sort(key=_slot_order_key)
        return [
            {**item, "product_index": index}
            for index, item in enumerate(filled)
        ]

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
                    normalize_product_fields(product, preserve_class=True),
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
            normalize_product_fields(product, preserve_class=True),
            qty=qty,
            unit=unit,
            qty_status=qty_status,
            boq_rate=boq_rate,
        )
        for product in products
    ]

