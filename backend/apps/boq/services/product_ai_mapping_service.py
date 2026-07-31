"""AI layer: map extracted products to Rate_Master_Output rows and attributes."""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any

from ai.context import align_product_taxonomy_from_db_labels, align_product_taxonomy_from_rate
from ai.service import AIService
from apps.boq.services.product_matching_service import (
    ProductMatchingService,
    structured_match_score,
)
from apps.database_manager.models import Rate_Master_Output
from common.constants import MATCH_CONFIDENCE_THRESHOLD, REFINE_MATCH_CONFIDENCE_TARGET
from utils.attribute_parser import (
    normalize_attribute_key,
    normalize_attribute_value,
    parse_attributes,
    coerce_attributes_dict,
)

from .product_attribute_enrichment_service import (
    compute_attribute_confidence,
    merge_attributes_onto_schema,
)

logger = logging.getLogger("boq_ai")


def _mapping_batch_size() -> int:
    from django.conf import settings

    return max(1, int(getattr(settings, "AI_PRODUCT_MAPPING_BATCH_SIZE", 4) or 4))


# Analysis UI + AI payload: only the best few Rate_Master_Output neighbors.
_CANDIDATE_LIMIT = 3
# Chroma recall pool before ranking down to _CANDIDATE_LIMIT.
_RECALL_CHROMA_LIMIT = 30
_REFINE_CHROMA_LIMIT = 30
_REFINE_PASSES = 1

DB_MATCH_MATCHED = "matched"
DB_MATCH_PROVISIONAL = "provisional"
DB_MATCH_UNMATCHED = "unmatched"


def product_needs_match_refine(
    product: dict[str, Any],
    *,
    min_confidence: float = REFINE_MATCH_CONFIDENCE_TARGET,
) -> bool:
    """True when a second mapping pass (like Re-analyse) may improve the match."""
    status = str(product.get("db_match_status") or "").strip().lower()
    if status != DB_MATCH_MATCHED:
        return True
    try:
        confidence = float(product.get("db_match_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence < float(min_confidence)


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _missing_attribute_keys(schema_keys: list[str], attributes: dict[str, Any]) -> list[str]:
    return [
        key
        for key in schema_keys
        if not _is_filled((attributes or {}).get(key))
    ]


def _json_scalar(value: Any) -> Any:
    """Convert model values (e.g. Decimal) to JSON-safe scalars for analysis_data."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _slim_candidate(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Store/display candidate without inventing fields."""
    return {
        "id": snapshot.get("id"),
        "product_id": snapshot.get("product_id"),
        "rate_id": snapshot.get("rate_id"),
        "tech_key": snapshot.get("tech_key"),
        "category": snapshot.get("category"),
        "sub_category": snapshot.get("sub_category"),
        "class": snapshot.get("class"),
        "size": _json_scalar(snapshot.get("size")),
        "unit": snapshot.get("unit"),
        "capacity": _json_scalar(snapshot.get("capacity")),
        "make": snapshot.get("make"),
        "vendor": snapshot.get("vendor"),
        "attribute_schema": list(snapshot.get("attribute_schema") or []),
        "attributes": dict(snapshot.get("attributes") or {}),
        "confidence": _json_scalar(snapshot.get("confidence")),
        "summary": _product_summary(snapshot),
    }


def _prefer_candidate_first(
    candidates: list[dict[str, Any]],
    selected_id: int | None,
) -> list[dict[str, Any]]:
    """Move the selected/suggested candidate to index 0 when present."""
    if selected_id in (None, ""):
        return list(candidates)
    ordered: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for item in candidates:
        try:
            if int(item.get("id") or 0) == int(selected_id):
                selected = item
                continue
        except (TypeError, ValueError):
            pass
        ordered.append(item)
    if selected is not None:
        return [selected, *ordered]
    return ordered


def _candidate_snapshot(
    rate: Rate_Master_Output,
    *,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Serialize a Rate_Master_Output row for AI/mapping.

    ``id`` / ``rate_master_id`` are both ``Rate_Master_Output.id`` (Django PK). There is
    no ``rate_master_id`` column on the table — that name is only a JSON alias.
    """
    attrs = parse_attributes(rate.Attribute)
    return {
        "id": rate.pk,
        "rate_master_id": rate.pk,  # alias of id for older callers
        "product_id": rate.Product_ID,
        "rate_id": rate.Rate_ID,
        "tech_key": rate.display_key(),
        "category": rate.Category,
        "sub_category": rate.Sub_Category,
        "class": rate.Class,
        "size": _json_scalar(rate.Size),
        "unit": rate.Unit,
        "capacity": _json_scalar(rate.Capacity),
        "make": rate.Make,
        "vendor": rate.Vendor,
        "attribute_schema": list(attrs.keys()),
        "attributes": attrs,
        "confidence": confidence,
    }


def _product_summary(snapshot: dict[str, Any]) -> str:
    # Intentionally omit make — Analysis finds the product; Make & Vendor selects make.
    parts = [
        snapshot.get("category"),
        snapshot.get("sub_category"),
        snapshot.get("class"),
        snapshot.get("size"),
    ]
    return " / ".join(str(part).strip() for part in parts if _is_filled(part)) or "Matched product"


def _normalize_attr_dict(raw: Any) -> dict[str, str]:
    return coerce_attributes_dict(raw)


def _compute_match_confidence(
    extracted: dict[str, Any],
    rate: Rate_Master_Output,
    *,
    mapped_attributes: dict[str, str],
    schema_keys: list[str],
    ai_confidence: float | None,
) -> float:
    """Blend structured product score with attribute fill — never make/vendor."""
    product_only = dict(extracted)
    product_only["make_hint"] = None
    structured, _breakdown = structured_match_score(product_only, rate)

    skip_keys = {"make", "manufacturer", "brand", "supplier", "vendor"}
    product_schema = [
        key for key in schema_keys if _normalize_text_key(key) not in skip_keys
    ]
    product_mapped = {
        key: value
        for key, value in (mapped_attributes or {}).items()
        if _normalize_text_key(key) not in skip_keys
    }
    db_attrs = {
        key: value
        for key, value in (parse_attributes(rate.Attribute) or {}).items()
        if _normalize_text_key(key) not in skip_keys
    }
    attr_score = compute_attribute_confidence(
        product_schema,
        product_mapped,
        db_attrs=db_attrs or None,
    )
    if product_schema:
        blended = (0.55 * structured) + (0.45 * attr_score)
    else:
        blended = structured
    if ai_confidence is not None:
        blended = (0.7 * blended) + (0.3 * float(ai_confidence))
    return round(max(0.0, min(100.0, blended)), 2)


def _normalize_text_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _map_attrs_onto_schema(
    *,
    schema_keys: list[str],
    extracted_attrs: dict[str, str],
    attribute_map: dict[str, str],
    mapped_attributes: dict[str, str],
    unmapped_attributes: dict[str, str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Resolve AI + extracted attributes onto a Rate_Master_Output Attribute schema."""
    from utils.attribute_parser import build_alias_map, resolve_to_schema_key

    alias_map = build_alias_map(schema_keys)
    attr_map = dict(attribute_map)
    mapped = dict(mapped_attributes)
    unmapped = dict(unmapped_attributes)

    if attr_map:
        attr_map = {
            src: (resolve_to_schema_key(dst, schema_keys, aliases=alias_map) or dst)
            for src, dst in attr_map.items()
        }

    if mapped:
        resolved_mapped: dict[str, str] = {}
        for key, value in mapped.items():
            schema_key = resolve_to_schema_key(key, schema_keys, aliases=alias_map) or key
            if schema_key in schema_keys:
                resolved_mapped[schema_key] = value
            else:
                unmapped.setdefault(key, value)
        mapped = resolved_mapped

    if not mapped and attr_map:
        for src, dst in attr_map.items():
            if src in extracted_attrs and dst in schema_keys:
                mapped[dst] = extracted_attrs[src]

    if not mapped:
        merged_all = merge_attributes_onto_schema(
            schema_keys=schema_keys,
            extracted_attrs=extracted_attrs,
        )
        mapped = {key: value for key, value in merged_all.items() if key in schema_keys}
        unmapped = {key: value for key, value in merged_all.items() if key not in schema_keys}
    elif not unmapped:
        mapped_keys = set(mapped)
        mapped_keys.update(attr_map.values())
        unmapped = {
            key: value
            for key, value in extracted_attrs.items()
            if key not in mapped_keys
            and resolve_to_schema_key(key, schema_keys, aliases=alias_map) is None
        }

    return mapped, unmapped, attr_map


class ProductAIMappingService:
    """
    Retrieve Rate_Master_Output candidates, then use AI to select the product and map
    extracted attributes onto the DB Attribute schema for Analysis review.

    Never invents Rate_Master_Output rows or Product_ID values. Attaches a DB product only
    when AI selects a candidate or service confidence meets the match threshold.
    Weak top candidates may supply a provisional attribute schema for gap-fill,
    without claiming a confirmed match.
    """

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id
        self._matcher = ProductMatchingService(database_version_id)
        self._ai = AIService()

    def map_product(self, product: dict[str, Any]) -> dict[str, Any]:
        results = self.map_products([product])
        return results[0] if results else self._fallback_without_match(product)

    def apply_selected_candidate(
        self,
        product: dict[str, Any],
        rate_master_id: int,
    ) -> dict[str, Any]:
        """
        Expert override: confirm a Rate_Master_Output candidate from Analysis.

        Maps product attributes onto that row's Attribute schema and marks the
        product as matched (user choice), keeping other candidates for re-pick.
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
        for item in existing_candidates:
            if not isinstance(item, dict):
                continue
            try:
                item_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            if item_id == selected_pk:
                preserved = dict(item)
                preserved.update(selected_slim)
                # Keep prior retrieval % when present; blended score applied below.
                if item.get("confidence") is not None and selected_slim.get("confidence") is None:
                    preserved["confidence"] = item.get("confidence")
                candidates.append(preserved)
            else:
                candidates.append(dict(item))
            if len(candidates) >= _CANDIDATE_LIMIT:
                break
        if selected_pk not in seen_ids:
            candidates.insert(0, selected_slim)
            candidates = candidates[:_CANDIDATE_LIMIT]

        extracted_attrs = coerce_attributes_dict(product.get("attributes"))
        schema_keys = list(snapshot.get("attribute_schema") or [])
        mapped_attributes, _unmapped, attribute_map = _map_attrs_onto_schema(
            schema_keys=schema_keys,
            extracted_attrs=extracted_attrs,
            attribute_map={},
            mapped_attributes={},
            unmapped_attributes=dict(extracted_attrs),
        )
        schema_set = {normalize_attribute_key(key) for key in schema_keys}
        attributes = {
            key: value
            for key, value in mapped_attributes.items()
            if normalize_attribute_key(str(key)) in schema_set and _is_filled(value)
        }
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
        return align_product_taxonomy_from_rate(enriched, rate, overwrite_core_fields=False)

    def map_products(
        self,
        products: list[dict[str, Any]],
        *,
        refine: bool = False,
    ) -> list[dict[str, Any]]:
        if not products:
            return []

        chroma_limit = _RECALL_CHROMA_LIMIT
        # Batch embedding recall — one OpenAI embeddings call for the whole chunk.
        recall_inputs = []
        for product in products:
            product_for_recall = dict(product)
            product_for_recall["make_hint"] = None
            recall_inputs.append(product_for_recall)
        matches = self._matcher.match_products_batch(
            recall_inputs,
            chroma_limit=max(int(chroma_limit or _RECALL_CHROMA_LIMIT), _RECALL_CHROMA_LIMIT),
        )

        prepared: list[dict[str, Any]] = []
        for index, (product, match) in enumerate(zip(products, matches, strict=False)):
            candidates = self._snapshots_from_match(match, product)
            prepared.append(
                {
                    "product_ref": f"p{index}",
                    "extracted": self._extracted_payload(product),
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

        mapped: list[dict[str, Any]] = []
        for item in prepared:
            ai_result = ai_by_ref.get(item["product_ref"])
            mapped.append(
                self._apply_mapping(
                    item["source_product"],
                    item["candidates"],
                    ai_result,
                )
            )
        return mapped

    def map_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        only_missing: bool = False,
        only_weak: bool = False,
        refine: bool = False,
        min_confidence: float = REFINE_MATCH_CONFIDENCE_TARGET,
        progress_callback=None,
    ) -> list[dict[str, Any]]:
        from .product_attribute_enrichment_service import product_needs_attribute_enrichment

        pending: list[tuple[int, int, dict[str, Any]]] = []
        for row_index, row in enumerate(rows):
            for product_index, product in enumerate(row.get("products") or []):
                if only_missing and not product_needs_attribute_enrichment(product):
                    continue
                if only_weak and not product_needs_match_refine(
                    product, min_confidence=min_confidence
                ):
                    continue
                pending.append((row_index, product_index, product))

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
            try:
                mapped_products.extend(self.map_products(chunk_products, refine=refine))
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

        updated_rows = [dict(row) for row in rows]
        for (row_index, product_index, _product), mapped in zip(pending, mapped_products, strict=False):
            products = list(updated_rows[row_index].get("products") or [])
            products[product_index] = mapped
            updated_rows[row_index] = {**updated_rows[row_index], "products": products}
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

        Single strong pass — used after expert attribute edits. Does not stack
        automatic refine passes (those inflated confidence without input changes).
        """
        return self.map_rows(rows, only_missing=False)

    def _seed_candidates(self, product: dict[str, Any]) -> list[tuple[int, Any]]:
        """Prior match/suggested ids with any stored retrieval confidence."""
        seeds: list[tuple[int, Any]] = []
        seen: set[int] = set()
        prior_confidence: dict[int, Any] = {}
        for item in product.get("db_candidates") or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("id")
            if raw in (None, ""):
                continue
            try:
                rate_id = int(raw)
            except (TypeError, ValueError):
                continue
            if item.get("confidence") is not None:
                prior_confidence[rate_id] = item.get("confidence")

        def _add(rate_id: int) -> None:
            if rate_id in seen:
                return
            seen.add(rate_id)
            seeds.append((rate_id, prior_confidence.get(rate_id)))

        for key in ("db_product_id", "suggested_db_product_id"):
            raw = product.get(key)
            if raw in (None, ""):
                continue
            try:
                _add(int(raw))
            except (TypeError, ValueError):
                continue
        for rate_id in prior_confidence:
            _add(rate_id)
            if len(seeds) >= _CANDIDATE_LIMIT:
                break
        # Also keep prior candidates that had no confidence stored.
        for item in product.get("db_candidates") or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("id")
            if raw in (None, ""):
                continue
            try:
                _add(int(raw))
            except (TypeError, ValueError):
                continue
            if len(seeds) >= _CANDIDATE_LIMIT:
                break
        return seeds

    def _recall_candidates(
        self,
        product: dict[str, Any],
        *,
        chroma_limit: int = _RECALL_CHROMA_LIMIT,
    ) -> list[dict[str, Any]]:
        # Analysis finds the product without make — Make & Vendor selects make later.
        product_for_recall = dict(product)
        product_for_recall["make_hint"] = None
        match = self._matcher.match_product(
            product_for_recall,
            chroma_limit=max(int(chroma_limit or _RECALL_CHROMA_LIMIT), _RECALL_CHROMA_LIMIT),
        )
        return self._snapshots_from_match(match, product)

    def _snapshots_from_match(
        self,
        match: dict[str, Any],
        product: dict[str, Any],
    ) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        seen: set[int] = set()

        def _confidence_value(raw: Any) -> float:
            try:
                return float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        rate_ids: list[int] = []
        confidences: dict[int, Any] = {}
        for item in match.get("candidates") or []:
            rate_id = item.get("rate_master_id")
            if rate_id in (None, ""):
                continue
            try:
                rid = int(rate_id)
            except (TypeError, ValueError):
                continue
            if rid in seen:
                if _confidence_value(item.get("confidence")) >= _confidence_value(
                    confidences.get(rid)
                ):
                    confidences[rid] = item.get("confidence")
                continue
            seen.add(rid)
            rate_ids.append(rid)
            confidences[rid] = item.get("confidence")
            if len(rate_ids) >= _CANDIDATE_LIMIT:
                break

        rate_map = {
            rate.pk: rate
            for rate in Rate_Master_Output.objects.filter(
                pk__in=rate_ids,
                database_version_id=self.database_version_id,
            )
        }
        for rid in rate_ids:
            rate = rate_map.get(rid)
            if rate is None:
                continue
            snapshots.append(_candidate_snapshot(rate, confidence=confidences.get(rid)))

        if not snapshots:
            for item in self._matcher._sql_fallback_candidates(product):
                rate = item.get("rate")
                if rate is None:
                    continue
                snapshots.append(
                    _candidate_snapshot(rate, confidence=item.get("confidence"))
                )
                if len(snapshots) >= _CANDIDATE_LIMIT:
                    break

        snapshots.sort(
            key=lambda item: _confidence_value(item.get("confidence")),
            reverse=True,
        )
        return snapshots[:_CANDIDATE_LIMIT]

    def _run_ai_batches(self, prepared: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Call map_product_match with ``{{PRODUCTS_PAYLOAD}}`` filled from recall.

        PRODUCTS_PAYLOAD is built here (not loaded from a file): a JSON list of
        ``{product_ref, extracted, candidates[]}`` for the current batch.
        Each candidate ``id`` is ``Rate_Master_Output.id`` (table PK).
        """
        template = AIService.load_prompt("map_product_match.txt")
        by_ref: dict[str, dict[str, Any]] = {}
        batch_size = _mapping_batch_size()
        for start in range(0, len(prepared), batch_size):
            batch = prepared[start : start + batch_size]
            payload = [
                {
                    "product_ref": item["product_ref"],
                    "extracted": item["extracted"],
                    "candidates": [
                        {
                            "id": candidate["id"],
                            "product_id": candidate.get("product_id"),
                            "rate_id": candidate.get("rate_id"),
                            "tech_key": candidate.get("tech_key"),
                            "category": candidate.get("category"),
                            "sub_category": candidate.get("sub_category"),
                            "class": candidate.get("class"),
                            "size": candidate.get("size"),
                            "unit": candidate.get("unit"),
                            "capacity": candidate.get("capacity"),
                            # Omit make — Analysis confidence is product-only.
                            "attribute_schema": [
                                key
                                for key in (candidate.get("attribute_schema") or [])
                                if _normalize_text_key(str(key))
                                not in {"make", "manufacturer", "brand", "supplier", "vendor"}
                            ],
                            "attributes": {
                                key: value
                                for key, value in (candidate.get("attributes") or {}).items()
                                if _normalize_text_key(str(key))
                                not in {"make", "manufacturer", "brand", "supplier", "vendor"}
                            },
                            "retrieval_confidence": candidate.get("confidence"),
                        }
                        for candidate in item["candidates"]
                    ],
                }
                for item in batch
                if item["candidates"]
            ]
            if not payload:
                continue
            prompt = template.replace(
                "{{PRODUCTS_PAYLOAD}}",
                json.dumps(payload, ensure_ascii=False, default=str),
            )
            response = self._ai.complete_json(prompt, template_name="map_product_match.txt")
            for entry in response.get("products") or []:
                ref = str(entry.get("product_ref") or "")
                if ref:
                    by_ref[ref] = entry
        return by_ref

    def _apply_mapping(
        self,
        product: dict[str, Any],
        candidates: list[dict[str, Any]],
        ai_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        enriched = dict(product)
        extracted_attrs = coerce_attributes_dict(product.get("attributes"))
        candidate_by_id = {
            int(item["id"]): item
            for item in candidates
            if item.get("id") is not None
        }
        slim_candidates = [_slim_candidate(item) for item in candidates]

        selected_id = None
        attribute_map: dict[str, str] = {}
        mapped_attributes: dict[str, str] = {}
        unmapped_attributes: dict[str, str] = dict(extracted_attrs)
        ai_confidence = None
        notes = ""

        if ai_result:
            # Accept selected_id (preferred) or legacy selected_rate_master_id.
            raw_id = ai_result.get("selected_id")
            if raw_id in (None, ""):
                raw_id = ai_result.get("selected_rate_master_id")
            try:
                selected_id = int(raw_id) if raw_id not in (None, "") else None
            except (TypeError, ValueError):
                selected_id = None
            if selected_id not in candidate_by_id:
                selected_id = None

            attribute_map = {
                normalize_attribute_key(str(src)): normalize_attribute_key(str(dst))
                for src, dst in (ai_result.get("attribute_map") or {}).items()
                if str(src).strip() and str(dst).strip()
            }
            mapped_attributes = _normalize_attr_dict(ai_result.get("mapped_attributes"))
            unmapped_attributes = _normalize_attr_dict(ai_result.get("unmapped_attributes"))
            try:
                raw_confidence = ai_result.get("match_confidence")
                ai_confidence = float(raw_confidence) if raw_confidence is not None else None
            except (TypeError, ValueError):
                ai_confidence = None
            notes = str(ai_result.get("notes") or "").strip()

        # Never invent a product. Prefer AI selection; otherwise only score the top
        # retrieval candidate when structured fields already look plausible.
        if selected_id is None and candidates:
            top = candidates[0]
            top_rate = Rate_Master_Output.objects.filter(
                pk=top["id"],
                database_version_id=self.database_version_id,
            ).first()
            if top_rate is not None:
                structured, _ = structured_match_score(enriched, top_rate)
                if structured >= MATCH_CONFIDENCE_THRESHOLD:
                    selected_id = int(top["id"])

        if selected_id is None:
            return self._fallback_without_match(
                enriched,
                extracted_attrs,
                candidates=slim_candidates,
                notes=notes or "No Rate_Master_Output candidate selected.",
            )

        snapshot = candidate_by_id.get(selected_id)
        rate = Rate_Master_Output.objects.filter(
            pk=selected_id,
            database_version_id=self.database_version_id,
        ).first()
        if rate is None:
            return self._fallback_without_match(
                enriched,
                extracted_attrs,
                candidates=slim_candidates,
                notes="Selected Rate_Master_Output row not found.",
            )

        schema_keys = list(
            (snapshot or {}).get("attribute_schema") or parse_attributes(rate.Attribute).keys()
        )
        mapped_attributes, unmapped_attributes, attribute_map = _map_attrs_onto_schema(
            schema_keys=schema_keys,
            extracted_attrs=extracted_attrs,
            attribute_map=attribute_map,
            mapped_attributes=mapped_attributes,
            unmapped_attributes=unmapped_attributes,
        )

        # BOQ is source of truth: fill any remaining schema keys from extracted attrs.
        schema_merged = merge_attributes_onto_schema(
            schema_keys=schema_keys,
            extracted_attrs=extracted_attrs,
        )
        for key, value in schema_merged.items():
            if key in schema_keys and key not in mapped_attributes and _is_filled(value):
                mapped_attributes[key] = value

        # Persist only required DB schema attributes — never keep additional/unmapped keys.
        schema_set = {normalize_attribute_key(key) for key in schema_keys}
        attributes = {
            key: value
            for key, value in mapped_attributes.items()
            if normalize_attribute_key(str(key)) in schema_set and _is_filled(value)
        }
        confidence = _compute_match_confidence(
            enriched,
            rate,
            mapped_attributes=attributes,
            schema_keys=schema_keys,
            ai_confidence=ai_confidence,
        )
        summary_source = snapshot or _candidate_snapshot(rate, confidence=confidence)
        missing_keys = _missing_attribute_keys(schema_keys, attributes)
        # Keep % visible on the selected row in Top database candidates.
        for item in slim_candidates:
            try:
                if int(item.get("id") or 0) == int(rate.pk):
                    item["confidence"] = confidence
                    break
            except (TypeError, ValueError):
                continue
        # Selected / suggested product first so Analysis UI shows the best pick on top.
        slim_candidates = _prefer_candidate_first(slim_candidates, rate.pk)

        # Confirm only when blended confidence clears the threshold — never stamp
        # Product identity from a weak / unrelated candidate.
        if confidence < MATCH_CONFIDENCE_THRESHOLD:
            return self._provisional_schema_match(
                enriched,
                rate=rate,
                snapshot=summary_source,
                schema_keys=schema_keys,
                attributes=attributes,
                mapped_attributes=attributes,
                missing_keys=missing_keys,
                confidence=confidence,
                candidates=slim_candidates,
                attribute_map=attribute_map,
                notes=notes or "Suggested DB product — fill missing attributes, then Re-analyse.",
                ai_confidence=ai_confidence,
            )

        enriched["attributes"] = attributes
        enriched["attribute_schema"] = schema_keys
        enriched["missing_attribute_keys"] = missing_keys
        enriched["attribute_confidence"] = confidence
        enriched["attribute_source"] = "database" if schema_keys else "extracted"
        enriched["db_match_status"] = DB_MATCH_MATCHED
        enriched["db_product_id"] = rate.pk
        # Keep make off Analysis UI; Make & Vendor owns vendor selection.
        enriched["db_product_make"] = ""
        enriched["db_product_tech_key"] = rate.display_key()
        enriched["db_match_confidence"] = confidence
        enriched["db_product_summary"] = _product_summary(summary_source)
        enriched["suggested_db_product_id"] = rate.pk
        enriched["db_candidates"] = slim_candidates
        enriched["ai_mapping"] = {
            "selected_id": rate.pk,
            "selected_rate_master_id": rate.pk,
            "attribute_map": attribute_map,
            "notes": notes,
            "ai_confidence": ai_confidence,
            "candidate_ids": [item["id"] for item in candidates],
            "match_status": DB_MATCH_MATCHED,
        }
        # Keep BOQ-extracted class/size/unit/capacity; only fill blanks from DB.
        return align_product_taxonomy_from_rate(enriched, rate, overwrite_core_fields=False)

    def _provisional_schema_match(
        self,
        product: dict[str, Any],
        *,
        rate: Rate_Master_Output,
        snapshot: dict[str, Any],
        schema_keys: list[str],
        attributes: dict[str, str],
        mapped_attributes: dict[str, str],
        missing_keys: list[str],
        confidence: float,
        candidates: list[dict[str, Any]],
        attribute_map: dict[str, str],
        notes: str,
        ai_confidence: float | None,
    ) -> dict[str, Any]:
        """Offer top-candidate Attribute schema for gap-fill without confirming tech_key."""
        enriched = dict(product)
        # Attribute fill score only — do not claim a confirmed DB product match.
        attr_only = compute_attribute_confidence(
            schema_keys,
            mapped_attributes,
            db_attrs=parse_attributes(rate.Attribute) or None,
        )
        enriched["attributes"] = attributes
        enriched["attribute_schema"] = schema_keys
        enriched["missing_attribute_keys"] = missing_keys
        enriched["attribute_confidence"] = attr_only
        enriched["attribute_source"] = "database" if schema_keys else "extracted"
        enriched["db_match_status"] = DB_MATCH_PROVISIONAL
        # Do not stamp confirmed tech_key / product id — user fills gaps then rematches.
        enriched["db_product_id"] = None
        enriched["db_product_make"] = ""
        enriched["db_product_tech_key"] = ""
        enriched["db_match_confidence"] = confidence
        enriched["db_product_summary"] = f"Suggested: {_product_summary(snapshot)}"
        enriched["suggested_db_product_id"] = rate.pk
        slim = [_slim_candidate(item) for item in candidates]
        for item in slim:
            try:
                if int(item.get("id") or 0) == int(rate.pk):
                    item["confidence"] = confidence
                    break
            except (TypeError, ValueError):
                continue
        enriched["db_candidates"] = _prefer_candidate_first(slim, rate.pk)
        enriched["ai_mapping"] = {
            "selected_id": None,
            "selected_rate_master_id": None,
            "suggested_id": rate.pk,
            "attribute_map": attribute_map,
            "notes": notes,
            "ai_confidence": ai_confidence,
            "candidate_ids": [item.get("id") for item in candidates],
            "match_status": DB_MATCH_PROVISIONAL,
        }
        return align_product_taxonomy_from_rate(enriched, rate, overwrite_core_fields=False)

    @staticmethod
    def _extracted_payload(product: dict[str, Any]) -> dict[str, Any]:
        return {
            "description_hint": product.get("description_hint"),
            "category": product.get("category"),
            "sub_category": product.get("sub_category"),
            "class": product.get("class"),
            "size": product.get("size"),
            "unit": product.get("unit"),
            "capacity": product.get("capacity"),
            # Analysis does not select make; omit hints so AI maps product only.
            "make_hint": None,
            "attributes": product.get("attributes") or {},
        }

    @staticmethod
    def _fallback_without_match(
        product: dict[str, Any],
        extracted_attrs: dict[str, str] | None = None,
        *,
        candidates: list[dict[str, Any]] | None = None,
        notes: str = "No Rate_Master_Output candidate selected.",
    ) -> dict[str, Any]:
        enriched = dict(product)
        attrs = extracted_attrs
        if attrs is None:
            attrs = coerce_attributes_dict(product.get("attributes"))

        # Prefer top candidate schema for empty keys to fill, without claiming a match.
        schema_keys: list[str] = []
        suggested_id = None
        summary = ""
        slim = list(candidates or [])
        if slim:
            top = slim[0]
            schema_keys = list(top.get("attribute_schema") or [])
            suggested_id = top.get("id")
            summary = f"Suggested: {top.get('summary') or _product_summary(top)}"
            if schema_keys:
                merged = merge_attributes_onto_schema(
                    schema_keys=schema_keys,
                    extracted_attrs=attrs,
                )
                # Schema keys only — drop any leftover extracted extras.
                schema_set = {normalize_attribute_key(key) for key in schema_keys}
                attrs = {
                    key: value
                    for key, value in merged.items()
                    if normalize_attribute_key(str(key)) in schema_set and _is_filled(value)
                }
                return ProductAIMappingService._provisional_from_candidate(
                    enriched,
                    attrs=attrs,
                    schema_keys=schema_keys,
                    suggested_id=suggested_id,
                    summary=summary,
                    candidates=slim,
                    notes=notes,
                )

        enriched["attributes"] = attrs
        enriched["attribute_schema"] = []
        enriched["missing_attribute_keys"] = []
        enriched["attribute_confidence"] = 0.0
        enriched["attribute_source"] = "extracted"
        enriched["db_match_status"] = DB_MATCH_UNMATCHED
        enriched["db_product_id"] = None
        enriched["db_product_make"] = ""
        enriched["db_product_tech_key"] = ""
        enriched["db_match_confidence"] = 0.0
        enriched["db_product_summary"] = ""
        enriched["suggested_db_product_id"] = None
        enriched["db_candidates"] = [_slim_candidate(item) for item in slim]
        enriched["ai_mapping"] = {
            "selected_id": None,
            "selected_rate_master_id": None,
            "attribute_map": {},
            "notes": notes,
            "ai_confidence": 0,
            "candidate_ids": [item.get("id") for item in slim],
            "match_status": DB_MATCH_UNMATCHED,
        }
        return enriched

    @staticmethod
    def _provisional_from_candidate(
        product: dict[str, Any],
        *,
        attrs: dict[str, str],
        schema_keys: list[str],
        suggested_id: Any,
        summary: str,
        candidates: list[dict[str, Any]],
        notes: str,
    ) -> dict[str, Any]:
        enriched = dict(product)
        missing = _missing_attribute_keys(schema_keys, attrs)
        enriched["attributes"] = attrs
        enriched["attribute_schema"] = schema_keys
        enriched["missing_attribute_keys"] = missing
        enriched["attribute_confidence"] = compute_attribute_confidence(schema_keys, attrs)
        enriched["attribute_source"] = "database" if schema_keys else "extracted"
        enriched["db_match_status"] = DB_MATCH_PROVISIONAL
        enriched["db_product_id"] = None
        enriched["db_product_make"] = ""
        enriched["db_product_tech_key"] = ""
        enriched["db_match_confidence"] = float((candidates[0] or {}).get("confidence") or 0)
        enriched["db_product_summary"] = summary
        enriched["suggested_db_product_id"] = suggested_id
        enriched["db_candidates"] = [_slim_candidate(item) for item in candidates]
        enriched["ai_mapping"] = {
            "selected_id": None,
            "selected_rate_master_id": None,
            "suggested_id": suggested_id,
            "attribute_map": {},
            "notes": notes,
            "ai_confidence": 0,
            "candidate_ids": [item.get("id") for item in candidates],
            "match_status": DB_MATCH_PROVISIONAL,
        }
        top = candidates[0] if candidates else {}
        return align_product_taxonomy_from_db_labels(
            enriched,
            category=top.get("category"),
            sub_category=top.get("sub_category"),
        )
