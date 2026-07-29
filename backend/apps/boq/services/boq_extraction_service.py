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

from apps.boq.services.boq_row_grouping_service import (
    anchor_qty_unit,
    grouped_anchor_rows,
    resolve_anchor_row_id,
    has_quantity,
)
from apps.boq.services.serial_normalizer import analysis_fields, letter_from_serial

logger = logging.getLogger("boq_ai")

_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_BATCH_SIZE = 4
_MAX_BATCH_CHARS = 14000

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
                len(current) >= _BATCH_SIZE
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
_MATERIAL_CLASS_ALIASES: dict[str, str] = {
    "ms": "MS",
    "m.s": "MS",
    "m.s.": "MS",
    "mild steel": "MS",
    "ms sheet": "MS Sheet",
    "ss": "SS",
    "s.s": "SS",
    "s.s.": "SS",
    "stainless steel": "SS",
    "ci": "CI",
    "c.i": "CI",
    "c.i.": "CI",
    "cast iron": "CI",
    "di": "DI",
    "d.i": "DI",
    "d.i.": "DI",
    "ductile iron": "DI",
    "gi": "GI",
    "g.i": "GI",
    "g.i.": "GI",
    "galvanised iron": "GI",
    "galvanized iron": "GI",
    "brass": "Brass",
    "grp": "GRP",
    "rubber": "Rubber",
    "forged steel": "Forged Steel",
}

_MATERIAL_ATTR_KEYS = frozenset(
    {"material", "body_material", "construction", "material_of_construction", "moc"}
)


def _normalize_class_material(value: Any) -> str | None:
    if _is_blank_value(value):
        return None
    text = str(value).strip()
    alias = _MATERIAL_CLASS_ALIASES.get(text.lower())
    return alias or text


def _promote_material_to_class(product: dict[str, Any]) -> dict[str, Any]:
    """Move attributes.material (and synonyms) onto product class for Rate_Master."""
    item = dict(product)
    attrs = coerce_attributes_dict(item.get("attributes"))
    material_value = None
    remaining: dict[str, Any] = {}
    for key, value in attrs.items():
        if str(key).strip().lower() in _MATERIAL_ATTR_KEYS and not _is_blank_value(value):
            if material_value is None:
                material_value = value
            continue
        remaining[key] = value

    if _is_blank_value(item.get("class")) and material_value is not None:
        item["class"] = _normalize_class_material(material_value)
    elif not _is_blank_value(item.get("class")):
        item["class"] = _normalize_class_material(item.get("class"))

    item["attributes"] = remaining
    return item


def _normalize_product_fields(product: dict[str, Any]) -> dict[str, Any]:
    """Normalize unit/qty UOM and promote material into class."""
    return _normalize_product_unit_fields(_promote_material_to_class(product))


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
    return {
        "row_id": group.get("row_id"),
        "serial": group.get("serial"),
        "depth": group.get("depth", 0),
        "description": group.get("full_description"),
        "lineage_lines": group.get("lineage_parts") or [],
        "qty": group.get("anchor_qty"),
        "unit": group.get("anchor_unit"),
        "qty_status": group.get("qty_status"),
        "rate_only": bool(group.get("rate_only")),
        "boq_rate": group.get("boq_rate"),
        "qty_rows": group.get("qty_rows") or [],
        "slots": group.get("slots") or [],
        "slot_count": int(group.get("slot_count") or len(group.get("slots") or [])),
        "heuristic_skip": should_skip_anchor_group(
            group,
            lineage_has_qty=bool(group.get("lineage_has_qty")),
        ),
    }


class BOQExtractionService:
    """Extract products from grouped BOQ anchor rows via OpenAI."""

    def __init__(self, boq_data: dict):
        self.boq_data = boq_data or {}
        self.ai = AIService()

    def extract(self, progress_callback=None) -> dict[str, Any]:
        if not self.ai.is_enabled():
            raise AIServiceError("OPENAI_API_KEY is not configured.")

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
        done = 0
        for batch in batches:
            for row in self._extract_batch(batch):
                row_id = row.get("row_id")
                if row_id:
                    extracted_by_id[str(row_id)] = row
            done += len(batch)
            if progress_callback:
                progress_callback(done, max(len(actionable_groups), 1))

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
        template = AIService.load_prompt("extract_products.txt")
        payload = [_compact_anchor_payload(group) for group in groups]
        prompt = (
            template.replace("{{DATABASE_CONTEXT}}", build_database_context())
            .replace("{{ROWS_PAYLOAD}}", json.dumps(payload, ensure_ascii=False, default=str))
        )
        response = self.ai.complete_json(prompt, template_name="extract_products.txt")
        rows = response.get("rows") or []
        if not isinstance(rows, list):
            raise AIServiceError("Extraction response missing rows list.")

        by_id = {row.get("row_id"): row for row in rows if row.get("row_id")}
        taxonomy = load_rate_master_taxonomy()
        normalized: list[dict[str, Any]] = []
        for group in groups:
            row_id = group.get("row_id")
            row = _resolve_batch_row(group, by_id)
            row.setdefault("row_id", row_id)
            products = _filter_spec_products(
                list(row.get("products") or []),
                taxonomy=taxonomy,
            )
            row["products"] = _apply_row_qty_unit(
                products,
                qty=group.get("anchor_qty"),
                unit=group.get("anchor_unit"),
                qty_status=group.get("qty_status"),
                boq_rate=group.get("boq_rate"),
                qty_rows=list(group.get("qty_rows") or []),
                slots=list(group.get("slots") or []),
            )
            row["activities"] = []
            row.setdefault("skip_matching", not row.get("products"))
            normalized.append(row)
        return normalized
