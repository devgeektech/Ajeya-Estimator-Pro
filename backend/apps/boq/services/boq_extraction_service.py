"""AI extraction of multiple products per grouped BOQ anchor row."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ai.context import build_database_context
from ai.service import AIService
from common.exceptions import AIServiceError

from apps.boq.services.boq_row_grouping_service import (
    anchor_qty_unit,
    grouped_anchor_rows,
    is_anchor_row,
    resolve_anchor_row_id,
)
from apps.boq.services.serial_normalizer import analysis_fields

logger = logging.getLogger("boq_ai")

_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_BATCH_SIZE = 4

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


def _has_quantity(fields: dict[str, Any]) -> bool:
    for key in _QTY_KEYS:
        value = fields.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)) and value != 0:
            return True
        text = str(value).strip()
        if text and text not in {"0", "0.0"}:
            return re.search(r"\d", text) is not None
    return False


def _lineage_has_quantity(rows: list[dict[str, Any]], lineage_ids: list[str]) -> bool:
    index = {str(row.get("row_id")): row for row in rows if row.get("row_id")}
    for row_id in lineage_ids:
        row = index.get(str(row_id))
        if row and _has_quantity(analysis_fields(row)):
            return True
    return False


def should_skip_anchor_group(group: dict[str, Any], *, lineage_has_qty: bool) -> bool:
    """Skip section-style anchor groups before calling AI."""
    full_text = str(group.get("full_description") or "").strip()
    if not full_text:
        return True

    anchor_fields = group.get("anchor_fields") or {}
    if _has_quantity(anchor_fields) or lineage_has_qty:
        return False

    if int(group.get("depth") or 0) == 0:
        return True

    return False


def _filter_spec_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [product for product in products if not _is_spec_only_product(product)]
    cleaned: list[dict[str, Any]] = []
    for index, product in enumerate(filtered):
        product = dict(product)
        product["product_index"] = index
        attrs = product.get("attributes")
        if isinstance(attrs, dict):
            product["attributes"] = {
                str(key): value
                for key, value in attrs.items()
                if value is not None and str(value).strip() != ""
            }
        for key in ("category", "sub_category", "class", "size", "unit", "capacity", "make_hint"):
            if key in product and product.get(key) is not None and str(product.get(key)).strip() == "":
                product[key] = None
        cleaned.append(product)
    return cleaned


def _consolidate_to_anchors(
    anchor_groups: list[dict[str, Any]],
    extracted_by_id: dict[str, dict[str, Any]],
) -> None:
    """Move products returned on lineage child row_ids onto the anchor row."""
    for group in anchor_groups:
        anchor_id = str(group.get("row_id") or "")
        if not anchor_id:
            continue
        lineage_ids = [str(row_id) for row_id in (group.get("lineage_ids") or [anchor_id])]

        merged_products: list[dict[str, Any]] = []
        merged_activities: list[str] = []
        for row_id in lineage_ids:
            row = extracted_by_id.get(row_id) or {}
            merged_products.extend(row.get("products") or [])
            for activity in row.get("activities") or []:
                if activity not in merged_activities:
                    merged_activities.append(activity)

        if not merged_products and not merged_activities:
            continue

        existing = extracted_by_id.get(anchor_id) or {}
        anchor_row: dict[str, Any] = {
            **existing,
            "row_id": anchor_id,
            "products": _filter_spec_products(merged_products),
            "activities": merged_activities,
            "skip_matching": not bool(merged_products),
        }
        anchor_row.pop("skip_reason", None)
        extracted_by_id[anchor_id] = anchor_row

        for row_id in lineage_ids:
            if row_id == anchor_id:
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

    for row_id in group.get("lineage_ids") or []:
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
        qty, unit = anchor_qty_unit(index, row_id)
        groups.append(
            {
                **group,
                "anchor_fields": analysis_fields(anchor_row),
                "lineage_has_qty": _lineage_has_quantity(rows, lineage_ids),
                "anchor_qty": qty,
                "anchor_unit": unit,
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
        "heuristic_skip": should_skip_anchor_group(
            group,
            lineage_has_qty=bool(group.get("lineage_has_qty")),
        ),
    }


class BOQExtractionService:
    """Extract products and activities from grouped BOQ anchor rows via OpenAI."""

    def __init__(self, boq_data: dict):
        self.boq_data = boq_data or {}
        self.ai = AIService()

    def extract(self) -> dict[str, Any]:
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
        for batch_start in range(0, len(actionable_groups), _BATCH_SIZE):
            batch = actionable_groups[batch_start : batch_start + _BATCH_SIZE]
            for row in self._extract_batch(batch):
                row_id = row.get("row_id")
                if row_id:
                    extracted_by_id[str(row_id)] = row

        _consolidate_to_anchors(anchor_groups, extracted_by_id)

        extracted_rows: list[dict[str, Any]] = []
        for row in flat_rows:
            row_id = row.get("row_id")
            if not row_id:
                continue

            if not is_anchor_row(row):
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

            group = next(
                (item for item in anchor_groups if str(item.get("row_id")) == str(row_id)),
                None,
            )
            if group and should_skip_anchor_group(
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
                    str(row_id),
                    {
                        "row_id": row_id,
                        "skip_matching": True,
                        "products": [],
                        "activities": [],
                        "skip_reason": "ai_missing_row",
                    },
                )
            )

        return {
            "schema_version": 1,
            "row_count": len(flat_rows),
            "extracted_row_count": len(extracted_rows),
            "rows": extracted_rows,
        }

    def extract_anchor(self, row_id: str) -> dict[str, Any]:
        """Extract products/activities for one anchor group (and its lineage stubs)."""
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
        if should_skip_anchor_group(group, lineage_has_qty=bool(group.get("lineage_has_qty"))):
            rows = [
                {
                    "row_id": lineage_ids[0],
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
                    for child_id in lineage_ids[1:]
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
        for lineage_id in lineage_ids:
            if lineage_id == anchor_id:
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
                        "row_id": lineage_id,
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
        normalized: list[dict[str, Any]] = []
        for group in groups:
            row_id = group.get("row_id")
            row = _resolve_batch_row(group, by_id)
            row.setdefault("row_id", row_id)
            row["products"] = _filter_spec_products(list(row.get("products") or []))
            row.setdefault("activities", [])
            row.setdefault("skip_matching", not row.get("products"))
            normalized.append(row)
        return normalized
