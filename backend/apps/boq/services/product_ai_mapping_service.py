"""AI layer: map extracted products to Rate_Master_Output rows and attributes."""
from __future__ import annotations

import logging
from typing import Any

from ai.context import align_product_taxonomy_from_rate
from ai.service import AIService
from apps.boq.services.product_ai_apply import ProductAIApplyMixin
from apps.boq.services.product_ai_candidates import ProductAICandidatesMixin
from apps.boq.services.product_ai_common import (
    DB_MATCH_MATCHED,
    DB_MATCH_PROVISIONAL,
    DB_MATCH_UNMATCHED,
    _AI_CANDIDATE_LIMIT,
    _CANDIDATE_LIMIT,
    _RECALL_CHROMA_LIMIT,
    _REFINE_PASSES,
    _REMATCH_CHROMA_LIMIT,
    _candidate_snapshot,
    _clear_weak_match_inputs,
    _compute_match_confidence,
    _mapping_batch_size,
    _missing_attribute_keys,
    _product_summary,
    _schema_attributes_from_rate,
    _should_blank_weak_match_inputs,
    _slim_candidate,
    product_needs_match_refine,
)
from apps.boq.services.product_matching_service import ProductMatchingService
from apps.database_manager.models import Rate_Master_Output
from common.constants import (
    REFINE_MATCH_CONFIDENCE_TARGET,
)
from utils.attribute_parser import coerce_attributes_dict


logger = logging.getLogger("boq_ai")

# Re-export for callers that import status constants / refine helper from this module.
__all__ = [
    "ProductAIMappingService",
    "product_needs_match_refine",
    "DB_MATCH_MATCHED",
    "DB_MATCH_PROVISIONAL",
    "DB_MATCH_UNMATCHED",
]


class ProductAIMappingService(
    ProductAIApplyMixin,
    ProductAICandidatesMixin,
):
    """
    Map BOQ extract products onto Rate_Master_Output candidates via AI.

    Candidate recall and AI apply live in sibling mixins; public method names on
    this class are unchanged for analysis / rematch / candidate Select.
    """


    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id
        self._matcher = ProductMatchingService(database_version_id)
        self._ai = AIService()


    def apply_selected_candidate(
        self,
        product: dict[str, Any],
        rate_master_id: int,
    ) -> dict[str, Any]:
        """
        Expert override: confirm a Rate_Master_Output candidate from Analysis.

        Prefills Analysis inputs from that Rate_Master row (category/class/size/
        unit/capacity + Attribute schema values) and marks the product matched.

        Confidence stays the candidate's listed retrieval/match % — do not
        recompute a blended score that jumps when switching candidates.
        """
        rate = Rate_Master_Output.objects.filter(
            pk=int(rate_master_id),
            database_version_id=self.database_version_id,
        ).first()
        if rate is None:
            raise ValueError(f"Unknown Rate_Master_Output id: {rate_master_id}")

        snapshot = _candidate_snapshot(rate)
        existing_candidates = list(product.get("db_candidates") or [])
        # Keep original candidate order — only flip selection, do not reshuffle
        # or mutate other candidate rows (that looked like “other candidates changed”).
        candidates: list[dict[str, Any]] = []
        selected_slim = _slim_candidate(snapshot)
        seen_ids: set[int] = set()
        selected_pk = int(rate.pk)
        listed_confidence: float | None = None
        for item in existing_candidates:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            if raw_id is None:
                continue
            try:
                item_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            if item_id == selected_pk:
                preserved = dict(item)
                preserved.update(selected_slim)
                # Keep the % that was shown on this candidate in the list.
                raw_confidence = item.get("confidence")
                if raw_confidence is not None:
                    preserved["confidence"] = raw_confidence
                    try:
                        listed_confidence = float(raw_confidence)
                    except (TypeError, ValueError):
                        listed_confidence = None
                candidates.append(preserved)
            else:
                # Never rewrite other candidates' scores or summaries on select.
                preserved = dict(item)
                raw_confidence = item.get("confidence")
                if raw_confidence is not None:
                    try:
                        preserved["confidence"] = float(raw_confidence)
                    except (TypeError, ValueError):
                        preserved["confidence"] = raw_confidence
                candidates.append(preserved)
            if len(candidates) >= _CANDIDATE_LIMIT:
                break
        if selected_pk not in seen_ids:
            candidates.insert(0, selected_slim)
            candidates = candidates[:_CANDIDATE_LIMIT]

        extracted_attrs = coerce_attributes_dict(product.get("attributes"))
        schema_keys = list(snapshot.get("attribute_schema") or [])
        rate_attrs = coerce_attributes_dict(snapshot.get("attributes"))
        # Prefill UI from the selected Rate_Master product; keep BOQ values only
        # where the DB row has no value for that schema key.
        attributes = _schema_attributes_from_rate(
            schema_keys=schema_keys,
            rate_attrs=rate_attrs,
            existing_attrs=extracted_attrs,
            prefer_rate=True,
        )
        attribute_map = {
            key: key for key in attributes if key in schema_keys
        }
        # Prefer the listed candidate % so switching tabs does not invent a new score.
        if listed_confidence is not None:
            confidence = round(max(0.0, min(100.0, listed_confidence)), 2)
        else:
            confidence = _compute_match_confidence(
                product,
                rate,
                mapped_attributes=attributes,
                schema_keys=schema_keys,
                ai_confidence=None,
            )
            for item in candidates:
                try:
                    if int(item.get("id") or 0) == selected_pk:
                        item["confidence"] = confidence
                        break
                except (TypeError, ValueError):
                    continue
        missing_keys = _missing_attribute_keys(schema_keys, attributes)

        enriched = dict(product)
        enriched["attributes"] = attributes
        enriched["attribute_schema"] = schema_keys
        enriched["missing_attribute_keys"] = missing_keys
        enriched["attribute_confidence"] = confidence
        enriched["attribute_source"] = "database" if schema_keys else "extracted"
        enriched["db_match_status"] = DB_MATCH_MATCHED
        enriched["db_product_id"] = rate.pk
        enriched["db_product_make"] = ""
        enriched["db_product_tech_key"] = rate.display_key()
        enriched["db_match_confidence"] = confidence
        enriched["db_product_summary"] = _product_summary(snapshot)
        enriched["suggested_db_product_id"] = rate.pk
        enriched["db_candidates"] = candidates
        enriched["ai_mapping"] = {
            "selected_id": rate.pk,
            "selected_rate_master_id": rate.pk,
            "attribute_map": attribute_map,
            "notes": "Selected by expert from top database candidates.",
            "ai_confidence": None,
            "candidate_ids": [item.get("id") for item in candidates],
            "match_status": DB_MATCH_MATCHED,
            "selection_source": "expert",
        }
        enriched["needs_extraction_review"] = False
        enriched["slot_fallback"] = False
        # Show fetched Rate_Master details in Analysis columns for the selected product.
        return self._attach_catalog_product_id(
            align_product_taxonomy_from_rate(enriched, rate, overwrite_core_fields=True)
        )


    def map_products(
        self,
        products: list[dict[str, Any]],
        *,
        refine: bool = False,
        blank_weak_inputs: bool = True,
    ) -> list[dict[str, Any]]:
        if not products:
            return []

        # Rematch / refine: wider Chroma pool so expert edits can surface new neighbors.
        chroma_limit = _REMATCH_CHROMA_LIMIT if refine else _RECALL_CHROMA_LIMIT
        recall_inputs = [
            self._product_for_recall(product, refine=refine) for product in products
        ]
        matches = self._matcher.match_products_batch(
            recall_inputs,
            chroma_limit=max(int(chroma_limit or _RECALL_CHROMA_LIMIT), _RECALL_CHROMA_LIMIT),
            result_limit=_AI_CANDIDATE_LIMIT,
        )

        prepared: list[dict[str, Any]] = []
        for index, (product, match) in enumerate(zip(products, matches, strict=False)):
            candidates = self._snapshots_from_match(match, product)
            if refine:
                # Merge priors only into leftover slots; never replace fresh recall.
                candidates = self._merge_seeded_candidates(product, candidates)
            prepared.append(
                {
                    "product_ref": f"p{index}",
                    "extracted": self._extracted_payload(product, rematch=refine),
                    "candidates": candidates,
                    "source_product": product,
                }
            )

        ai_by_ref: dict[str, dict[str, Any]] = {}
        if self._ai.is_enabled() and any(item["candidates"] for item in prepared):
            try:
                ai_by_ref = self._run_ai_batches(prepared)
            except Exception:
                logger.exception("AI product mapping failed; using structured fallback")

        # Rematch/refine never blanks mid-pass — callers blank after refine completes.
        do_blank = bool(blank_weak_inputs) and not refine
        mapped: list[dict[str, Any]] = []
        for item in prepared:
            ai_result = ai_by_ref.get(item["product_ref"])
            result = self._attach_catalog_product_id(
                self._apply_mapping(
                    item["source_product"],
                    item["candidates"],
                    ai_result,
                    rematch=refine,
                    blank_weak_inputs=do_blank,
                )
            )
            result.pop("_boq_row", None)
            result.pop("_prior_match", None)
            mapped.append(result)
        return mapped


    def map_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        only_missing: bool = False,
        only_weak: bool = False,
        refine: bool = False,
        min_confidence: float = REFINE_MATCH_CONFIDENCE_TARGET,
        blank_weak_inputs: bool = True,
        progress_callback=None,
    ) -> list[dict[str, Any]]:
        from .product_attribute_enrichment_service import product_needs_attribute_enrichment

        pending: list[tuple[int, int, dict[str, Any]]] = []
        for row_index, row in enumerate(rows):
            row_desc = str(
                row.get("description") or row.get("full_description") or ""
            ).strip()
            for product_index, product in enumerate(row.get("products") or []):
                if only_missing and not product_needs_attribute_enrichment(product):
                    continue
                if only_weak and not product_needs_match_refine(
                    product, min_confidence=min_confidence
                ):
                    continue
                work = dict(product)
                # Initial Analyse often lacks rematch's BOQ context — attach section
                # text when present so AI sees full meaning (Chroma still uses product
                # fields + slot line only via _product_for_recall).
                if "_boq_row" not in work and row_desc:
                    work["_boq_row"] = {
                        "row_id": row.get("row_id"),
                        "description": row_desc,
                        "slot_description": str(
                            product.get("description_hint") or ""
                        ).strip(),
                        "serial": row.get("serial") or row.get("ser_no") or "",
                    }
                pending.append((row_index, product_index, work))

        if not pending:
            if progress_callback:
                progress_callback(1, 1)
            return rows

        # Map in chunks so progress advances; embeddings are batched inside each chunk.
        chunk_size = max(_mapping_batch_size(), 4)
        mapped_products: list[dict[str, Any]] = []
        total = len(pending)
        if progress_callback:
            progress_callback(0, total)
        for start in range(0, total, chunk_size):
            chunk = pending[start : start + chunk_size]
            chunk_products = [item[2] for item in chunk]
            for _row_index, _product_index, product in chunk:
                logger.info(
                    "BOQ match product row=%s idx=%s category=%s sub=%s size=%s refine=%s",
                    (product.get("_boq_row") or {}).get("row_id")
                    or product.get("qty_row_id")
                    or product.get("source_row_id")
                    or "-",
                    product.get("product_index"),
                    product.get("category") or "-",
                    product.get("sub_category") or "-",
                    product.get("size") or "-",
                    refine,
                )
            try:
                mapped_products.extend(
                    self.map_products(
                        chunk_products,
                        refine=refine,
                        blank_weak_inputs=blank_weak_inputs,
                    )
                )
            except Exception:
                # Keep this chunk unmapped rather than discarding the whole BOQ's mapping.
                logger.exception(
                    "Product mapping chunk %s-%s failed; leaving those products unmapped",
                    start,
                    start + len(chunk),
                )
                mapped_products.extend(chunk_products)
            if progress_callback:
                progress_callback(min(total, start + len(chunk)), total)
            logger.info(
                "BOQ match chunk done %s/%s refine=%s",
                min(total, start + len(chunk)),
                total,
                refine,
            )

        updated_rows = [dict(row) for row in rows]
        for (row_index, product_index, _product), mapped in zip(pending, mapped_products, strict=False):
            products = list(updated_rows[row_index].get("products") or [])
            products[product_index] = mapped
            updated_rows[row_index] = {**updated_rows[row_index], "products": products}
        return updated_rows


    def apply_weak_match_blanking(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Blank Analysis inputs for weak matches after map + refine are done.

        Must run after refine — blanking earlier zeroes identity fields and
        rematch scores collapse to 0%.
        """
        updated_rows: list[dict[str, Any]] = []
        for row in rows:
            products: list[dict[str, Any]] = []
            for product in row.get("products") or []:
                if not isinstance(product, dict):
                    products.append(product)
                    continue
                confidence = float(
                    product.get("db_match_confidence")
                    or product.get("attribute_confidence")
                    or 0.0
                )
                if _should_blank_weak_match_inputs(
                    product, confidence=confidence, rematch=False
                ):
                    products.append(_clear_weak_match_inputs(product))
                else:
                    products.append(product)
            updated_rows.append({**row, "products": products})
        return updated_rows


    def refine_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        passes: int = _REFINE_PASSES,
        min_confidence: float = REFINE_MATCH_CONFIDENCE_TARGET,
        progress_callback=None,
    ) -> list[dict[str, Any]]:
        """
        Re-run matching on weak products after taxonomy/schema alignment.

        Same path as Analysis Re-analyse: uses updated category/sub-category/class
        and attribute schema from the first pass to improve recall and confidence.
        """
        updated = rows
        total_passes = max(1, int(passes or 1))
        for pass_index in range(total_passes):
            weak_before = sum(
                1
                for row in updated
                for product in (row.get("products") or [])
                if product_needs_match_refine(product, min_confidence=min_confidence)
            )
            if weak_before == 0:
                if progress_callback:
                    progress_callback(1, 1)
                break

            def _on_pass_progress(done: int, total: int, _pass=pass_index) -> None:
                if not progress_callback:
                    return
                # Stretch each refine pass across the callback range.
                span = max(total, 1)
                overall_done = (_pass * span) + done
                overall_total = total_passes * span
                progress_callback(overall_done, overall_total)

            updated = self.map_rows(
                updated,
                only_weak=True,
                refine=True,
                min_confidence=min_confidence,
                progress_callback=_on_pass_progress,
            )
        return updated


    def rematch_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Re-run DB candidate recall + AI mapping using current product fields/attrs.

        Used after expert edits on Analysis Re-analyse. Seeds prior Product_IDs /
        candidates into recall and weights filled blank attributes — does not
        re-extract from the BOQ workbook.
        """
        return self.map_rows(rows, only_missing=False, refine=True)


    def rematch_product(
        self,
        product: dict[str, Any],
        *,
        boq_row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Product-wise Re-analyse: rematch one product using UI fields + BOQ row context.

        Fresh Chroma/SQL recall with expert-edited fields, then AI picks the best
        Rate_Master neighbor and prefills Analysis inputs.
        """
        work = dict(product)
        # Stash prior match for the AI rematch payload only (not for locking recall).
        work["_prior_match"] = {
            "status": product.get("db_match_status"),
            "db_product_id": product.get("db_product_id")
            or product.get("suggested_db_product_id"),
            "catalog_product_id": product.get("catalog_product_id")
            or product.get("suggested_catalog_product_id"),
            "tech_key": product.get("db_product_tech_key"),
            "summary": product.get("db_product_summary"),
            "confidence": product.get("db_match_confidence"),
        }
        if boq_row:
            work["_boq_row"] = {
                "row_id": boq_row.get("row_id"),
                "description": boq_row.get("description")
                or boq_row.get("full_description")
                or "",
                "slot_description": boq_row.get("slot_description") or "",
                "serial": boq_row.get("serial") or boq_row.get("ser_no") or "",
            }
        # Drop locked match identity so rematch is driven by filled fields + fresh
        # recall. Prior candidates remain on ``db_candidates`` for leftover slots.
        for key in (
            "db_product_id",
            "suggested_db_product_id",
            "db_product_tech_key",
            "db_product_summary",
            "db_match_status",
            "db_match_confidence",
            "catalog_product_id",
            "suggested_catalog_product_id",
            "ai_mapping",
        ):
            work.pop(key, None)
        mapped = self.map_products([work], refine=True)
        result = mapped[0] if mapped else self._fallback_without_match(work)
        if isinstance(result, dict):
            result.pop("_prior_match", None)
            result.pop("_boq_row", None)
        return result

