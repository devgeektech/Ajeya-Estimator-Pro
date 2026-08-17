"""AI extraction of multiple products per grouped BOQ anchor row."""
from __future__ import annotations

import json
import logging
from typing import Any

from ai.context import build_database_context, load_rate_master_taxonomy, snap_product_taxonomy
from ai.service import AIService
from apps.boq.services.boq_extraction_fields import (
    _apply_row_qty_unit,
    _normalize_product_fields,
    normalize_product_fields,
    quantity_display_fields,
    rehydrate_analysis_rows_quantity,
    rehydrate_products_quantity_from_group,
)
from apps.boq.services.boq_extraction_groups import (
    _build_anchor_groups,
    _compact_anchor_payload,
    _consolidate_to_anchors,
    _extract_batch_size,
    _iter_extract_batches,
    _resolve_batch_row,
    should_skip_anchor_group,
)
from apps.boq.services.boq_extraction_slots import (
    _apply_slot_evidence_fields,
    _collapse_duplicate_slot_products,
    _ensure_minimum_slot_products,
    _filter_spec_products,
    _group_slots,
    _missing_product_slots,
)
from apps.boq.services.boq_row_grouping_service import resolve_anchor_row_id
from common.exceptions import AIServiceError
from utils.attribute_parser import coerce_attributes_dict
from utils.product_synonyms import format_synonym_map_for_ai

logger = logging.getLogger("boq_ai")


_MINIMUM_SLOT_RETRY_INSTRUCTION = """

CORRECTION — slot coverage required:
- Return ≥ slot_count products; every slots[].qty_row_id must appear on a product.
- Per-product size from that slot only; shared PN/seat/IS on all.
- ``description_hint`` = AI Description in plain English naming class/material,
  sub-category, category, size + unit, capacity and key attributes.
- Do not return two copies of the same product on one slot.
- Return the full corrected rows JSON.
"""


# Public re-exports for display / labour / analysis / make-vendor callers.
__all__ = [
    "BOQExtractionService",
    "normalize_product_fields",
    "quantity_display_fields",
    "rehydrate_analysis_rows_quantity",
    "rehydrate_products_quantity_from_group",
    "should_skip_anchor_group",
    "_normalize_product_fields",
]


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
        logger.info(
            "BOQ extract starting sections=%s batches=%s",
            extract_total,
            len(batches),
        )
        # Report 0/total immediately so the UI does not sit on a fake mid-band %.
        if progress_callback:
            progress_callback(0, extract_total)
        for batch_index, batch in enumerate(batches, start=1):
            row_ids = [str(group.get("row_id") or "") for group in batch]
            serials = [
                str(group.get("serial") or group.get("ser_no") or group.get("row_id") or "")
                for group in batch
            ]
            logger.info(
                "BOQ extract batch %s/%s rows=%s serials=%s",
                batch_index,
                len(batches),
                ",".join(row_ids) or "-",
                ",".join(serials) or "-",
            )
            for row in self._extract_batch(batch):
                row_id = row.get("row_id")
                products = row.get("products") or []
                logger.info(
                    "BOQ extract row done row_id=%s products=%s skip=%s",
                    row_id,
                    len(products),
                    bool(row.get("skip_matching")),
                )
                if row_id:
                    extracted_by_id[str(row_id)] = row
            done += len(batch)
            if progress_callback:
                progress_callback(done, extract_total)
            logger.info(
                "BOQ extract progress %s/%s sections complete",
                done,
                extract_total,
            )

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
            template.replace("{{SYNONYM_MAP}}", format_synonym_map_for_ai())
            .replace("{{DATABASE_CONTEXT}}", self._database_context_text())
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
            row["products"] = _collapse_duplicate_slot_products(
                _apply_slot_evidence_fields(
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
            )
            row["activities"] = []
            row.setdefault("skip_matching", not row.get("products"))
            normalized.append(row)
        return normalized

