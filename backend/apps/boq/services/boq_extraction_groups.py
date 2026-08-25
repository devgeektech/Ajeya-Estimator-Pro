"""Anchor grouping and extract-batch packing for BOQ extraction."""
from __future__ import annotations

import json
import re
from typing import Any

from ai.context import load_rate_master_taxonomy
from apps.boq.services.boq_extraction_slots import (
    _filter_spec_products,
)
from apps.boq.services.boq_row_grouping_service import (
    anchor_qty_unit,
    grouped_anchor_rows,
    has_quantity,
)
from apps.boq.services.serial_normalizer import analysis_fields, letter_from_serial


_MAX_BATCH_CHARS = 14000


def _extract_batch_size() -> int:
    from django.conf import settings

    return max(1, int(getattr(settings, "AI_ROW_EXTRACTION_BATCH_SIZE", 5) or 5))


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
    """Pack groups into AI batches by count and approximate payload size.

    Multi-slot sections always travel alone so product families do not leak
    across packages in one OpenAI JSON response.
    """
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for group in groups:
        payload = _compact_anchor_payload(group)
        size = len(json.dumps(payload, ensure_ascii=False))
        slot_count = int(group.get("slot_count") or len(group.get("slots") or []) or 0)
        # Multi-slot / mixed packages: one section per call for stable identity.
        if slot_count > 1:
            if current:
                batches.append(current)
                current = []
                current_chars = 0
            batches.append([group])
            continue
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
            "skip_matching": not bool(merged_products),
        }
        anchor_row.pop("skip_reason", None)
        anchor_row.pop("activities", None)
        anchor_row.pop("product_matches", None)
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
    """Compact section payload for extract — full section text + qty/unit slots."""
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
                # Owning supply sentence (product family). Prefer this over chapter title.
                "product_context": slot.get("product_context") or "",
            }
        )
    # Send the full lineage so the model understands the section (system title +
    # detail lines). Products still come only from ``slots`` (qty+unit rows).
    lineage = list(group.get("lineage_parts") or [])
    return {
        "row_id": group.get("row_id"),
        "serial": group.get("serial"),
        "description": group.get("full_description"),
        "lineage_lines": lineage,
        "slot_count": int(group.get("slot_count") or len(slots)),
        "slots": slots,
        "section_note": (
            "description/lineage_lines are CONTEXT only (system / chapter). "
            "Products only from slots. "
            "For each slot, category/sub_category/product noun come from "
            "slots[].product_context (owning supply sentence) + that slot — "
            "NOT from the chapter title alone (e.g. HYDRANT SYSTEM). "
            "Size-only slots (a) 150 mm dia) inherit the product family from "
            "product_context. "
            "Slots with unit Job/LS describing services (testing, commissioning, "
            "dismantling, painting, shop drawings) → skip_matching: true, products: []."
        ),
        "heuristic_skip": should_skip_anchor_group(
            group,
            lineage_has_qty=bool(group.get("lineage_has_qty")),
        ),
    }

