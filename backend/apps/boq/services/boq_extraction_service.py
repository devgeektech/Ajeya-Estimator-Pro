"""AI extraction of multiple products per BOQ row."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ai.context import build_database_context
from ai.service import AIService
from common.exceptions import AIServiceError

from .make_list_constraint_service import walk_rows_tree

logger = logging.getLogger("boq_ai")

_DESCRIPTION_KEYS = (
    "description",
    "item_description",
    "particulars",
    "item",
)
_QTY_KEYS = ("qty", "quantity", "qnty", "nos")
_BATCH_SIZE = 8


def _field_text(fields: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


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


def should_skip_row_heuristic(node: dict[str, Any]) -> bool:
    """Skip section-style rows before calling AI."""
    fields = node.get("fields") or {}
    description = _field_text(fields, _DESCRIPTION_KEYS)
    if not description:
        return True
    if node.get("depth", 0) == 0 and not _has_quantity(fields):
        return True
    return False


def _compact_row_payload(node: dict[str, Any]) -> dict[str, Any]:
    fields = node.get("fields") or {}
    return {
        "row_id": node.get("row_id"),
        "serial": node.get("serial"),
        "depth": node.get("depth", 0),
        "fields": fields,
        "heuristic_skip": should_skip_row_heuristic(node),
    }


class BOQExtractionService:
    """Extract products and activities from BOQ ``rows_tree`` via OpenAI."""

    def __init__(self, boq_data: dict):
        self.boq_data = boq_data or {}
        self.ai = AIService()

    def extract(self) -> dict[str, Any]:
        if not self.ai.is_enabled():
            raise AIServiceError("OPENAI_API_KEY is not configured.")

        tree = self.boq_data.get("rows_tree") or []
        nodes = walk_rows_tree(tree)
        actionable_nodes = [node for node in nodes if not should_skip_row_heuristic(node)]

        extracted_by_id: dict[str, dict[str, Any]] = {}
        for batch_start in range(0, len(actionable_nodes), _BATCH_SIZE):
            batch = actionable_nodes[batch_start : batch_start + _BATCH_SIZE]
            for row in self._extract_batch(batch):
                row_id = row.get("row_id")
                if row_id:
                    extracted_by_id[str(row_id)] = row

        extracted_rows: list[dict[str, Any]] = []
        for node in nodes:
            row_id = node.get("row_id")
            if not row_id:
                continue
            if should_skip_row_heuristic(node):
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
            "row_count": len(nodes),
            "extracted_row_count": len(extracted_rows),
            "rows": extracted_rows,
        }

    def _extract_batch(self, nodes: list[dict]) -> list[dict[str, Any]]:
        template = AIService.load_prompt("extract_products.txt")
        payload = [_compact_row_payload(node) for node in nodes]
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
        for node in nodes:
            row_id = node.get("row_id")
            row = by_id.get(row_id) or {
                "row_id": row_id,
                "skip_matching": True,
                "products": [],
                "activities": [],
                "skip_reason": "ai_missing_row",
            }
            row.setdefault("row_id", row_id)
            row.setdefault("products", [])
            row.setdefault("activities", [])
            row.setdefault("skip_matching", not row.get("products"))
            normalized.append(row)
        return normalized
