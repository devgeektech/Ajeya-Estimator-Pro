"""AI layer: map extracted products to Rate_Master_Output rows and attributes."""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any

from ai.context import (
    align_product_taxonomy_from_db_labels,
    align_product_taxonomy_from_rate,
    is_catalog_class,
)
from ai.service import AIService
from apps.boq.services.product_matching_service import (
    CANDIDATE_LIMIT,
    ProductMatchingService,
    product_type_conflicts,
    structured_match_score,
)
from apps.database_manager.models import Rate_Master_Output
from common.constants import MATCH_CONFIDENCE_THRESHOLD, REFINE_MATCH_CONFIDENCE_TARGET
from utils.attribute_parser import (
    normalize_attribute_key,
    parse_attributes,
    coerce_attributes_dict,
)
from utils.product_synonyms import display_material_label, is_known_material_label

from .product_attribute_enrichment_service import (
    compute_attribute_confidence,
    merge_attributes_onto_schema,
)

logger = logging.getLogger("boq_ai")


def _mapping_batch_size() -> int:
    from django.conf import settings

    return max(1, int(getattr(settings, "AI_PRODUCT_MAPPING_BATCH_SIZE", 4) or 4))


# Analysis UI + AI payload: top Rate_Master_Output neighbors.
_CANDIDATE_LIMIT = CANDIDATE_LIMIT
# Chroma recall pool before ranking down to _CANDIDATE_LIMIT.
_RECALL_CHROMA_LIMIT = 50
# Rematch (Re-analyse) uses a wider recall pool + prior Product_ID seeds.
_REMATCH_CHROMA_LIMIT = 80
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


_EXPERT_IDENTITY_FIELDS = (
    "description_hint",
    "category",
    "sub_category",
    "class",
    "size",
    "unit",
    "capacity",
)


def _restore_expert_identity(
    product: dict[str, Any],
    original: dict[str, Any],
) -> dict[str, Any]:
    """Keep expert-filled Analysis inputs after rematch (including Class=0)."""
    restored = dict(product)
    for key in _EXPERT_IDENTITY_FIELDS:
        value = original.get(key)
        if not _is_filled(value):
            continue
        if (
            key == "class"
            and is_known_material_label(value)
            and not is_catalog_class(
                value,
                category=restored.get("category") or original.get("category"),
                sub_category=restored.get("sub_category") or original.get("sub_category"),
            )
        ):
            # Keep Rate_Master Class (e.g. 0) instead of extracted material (DI).
            continue
        restored[key] = value
    return restored


def _missing_attribute_keys(schema_keys: list[str], attributes: dict[str, Any]) -> list[str]:
    return [
        key
        for key in schema_keys
        if not _is_filled((attributes or {}).get(key))
    ]


def _schema_attributes_from_rate(
    *,
    schema_keys: list[str],
    rate_attrs: dict[str, Any],
    existing_attrs: dict[str, Any] | None = None,
    prefer_rate: bool = False,
) -> dict[str, str]:
    """
    Build Analysis attribute inputs for a Rate_Master Attribute schema.

    ``prefer_rate=True`` (expert candidate select): show the selected DB product's
    values first so Category/attrs match the chosen row. Otherwise keep filled BOQ
    values and only fill blanks from Rate_Master.
    """
    rate_on_schema = merge_attributes_onto_schema(
        schema_keys=schema_keys,
        extracted_attrs=coerce_attributes_dict(rate_attrs),
    )
    existing_on_schema = merge_attributes_onto_schema(
        schema_keys=schema_keys,
        extracted_attrs=coerce_attributes_dict(existing_attrs or {}),
    )
    attributes: dict[str, str] = {}
    for key in schema_keys:
        rate_value = rate_on_schema.get(key)
        existing_value = existing_on_schema.get(key)
        if prefer_rate:
            if _is_filled(rate_value):
                attributes[key] = str(rate_value).strip()
            elif _is_filled(existing_value):
                attributes[key] = str(existing_value).strip()
        elif _is_filled(existing_value):
            attributes[key] = str(existing_value).strip()
        elif _is_filled(rate_value):
            attributes[key] = str(rate_value).strip()
    return attributes


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
        snapshot.get("unit"),
    ]
    return " / ".join(str(part).strip() for part in parts if _is_filled(part)) or "Matched product"


def _compute_match_confidence(
    extracted: dict[str, Any],
    rate: Rate_Master_Output,
    *,
    mapped_attributes: dict[str, str],
    schema_keys: list[str],
    ai_confidence: float | None,
    prefer_filled_fields: bool = False,
) -> float:
    """Blend structured product score with attribute fill — never make/vendor.

    ``prefer_filled_fields`` (Re-analyse): confidence follows how well the expert's
    filled UI fields match the Rate_Master row — AI may not drag it down for DI vs
    ductile iron wording.
    """
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

    if prefer_filled_fields:
        # Rematch: filled core fields dominate the shown %.
        if product_mapped:
            blended = (0.88 * structured) + (0.12 * float(attr_score or 0.0))
        else:
            blended = structured
        if ai_confidence is not None:
            blended = (0.92 * blended) + (0.08 * float(ai_confidence))
        if product_type_conflicts(product_only, rate):
            blended = min(blended, float(MATCH_CONFIDENCE_THRESHOLD) - 1.0)
        return round(max(0.0, min(100.0, blended)), 2)

    # Prefer product identity (cat/sub/class/size) over sparse attribute fill so
    # synonym edits like DI → ductile iron do not tank a strong nearest match.
    if structured >= 80:
        blended = (0.82 * structured) + (0.18 * (attr_score or structured))
    elif structured >= 60:
        blended = (0.70 * structured) + (0.30 * (attr_score or structured))
    elif product_schema:
        blended = (0.60 * structured) + (0.40 * attr_score)
    else:
        blended = structured
    if ai_confidence is not None:
        # AI may under-score synonym rewrites; keep structured dominant when strong.
        ai_weight = 0.15 if structured >= 75 else 0.30
        blended = ((1.0 - ai_weight) * blended) + (ai_weight * float(ai_confidence))
    # Description names a different catalog product — do not let AI/attr blend confirm it.
    if product_type_conflicts(product_only, rate):
        blended = min(blended, float(MATCH_CONFIDENCE_THRESHOLD) - 1.0)
    return round(max(0.0, min(100.0, blended)), 2)


def _normalize_text_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _downgrade_unrelated_auto_match(
    product: dict[str, Any],
    confidence: float,
) -> dict[str, Any]:
    """Clear a confirmed pick when description and catalog product disagree."""
    source = str((product.get("ai_mapping") or {}).get("selection_source") or "")
    if source == "expert":
        return product
    if confidence >= MATCH_CONFIDENCE_THRESHOLD:
        return product
    if str(product.get("db_match_status") or "") != DB_MATCH_MATCHED:
        return product
    updated = dict(product)
    updated["db_match_status"] = DB_MATCH_PROVISIONAL
    updated["db_product_id"] = None
    updated["db_product_tech_key"] = ""
    summary = str(updated.get("db_product_summary") or "").strip()
    if summary and not summary.lower().startswith("suggested:"):
        updated["db_product_summary"] = f"Suggested: {summary}"
    mapping = dict(updated.get("ai_mapping") or {})
    mapping["match_status"] = DB_MATCH_PROVISIONAL
    mapping["selected_id"] = None
    mapping["selected_rate_master_id"] = None
    updated["ai_mapping"] = mapping
    return updated


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
                # Keep the % that was shown on this candidate in the list.
                if item.get("confidence") is not None:
                    preserved["confidence"] = item.get("confidence")
                    try:
                        listed_confidence = float(item.get("confidence"))
                    except (TypeError, ValueError):
                        listed_confidence = None
                candidates.append(preserved)
            else:
                # Never rewrite other candidates' scores on select.
                candidates.append(dict(item))
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

        mapped: list[dict[str, Any]] = []
        for item in prepared:
            ai_result = ai_by_ref.get(item["product_ref"])
            result = self._attach_catalog_product_id(
                self._apply_mapping(
                    item["source_product"],
                    item["candidates"],
                    ai_result,
                    rematch=refine,
                )
            )
            result.pop("_boq_row", None)
            result.pop("_prior_match", None)
            mapped.append(result)
        return mapped

    def _product_for_recall(
        self,
        product: dict[str, Any],
        *,
        refine: bool = False,
    ) -> dict[str, Any]:
        """Build Chroma/SQL query input from UI fields (+ BOQ section on rematch)."""
        product_for_recall = dict(product)
        product_for_recall["make_hint"] = None
        # Normalize DI / ductile iron onto Rate_Master-style Class for SQL recall;
        # query text still expands both forms via build_match_query_text.
        for key in ("class", "sub_category"):
            raw = product_for_recall.get(key)
            if raw in (None, ""):
                continue
            display = display_material_label(raw)
            if display:
                product_for_recall[key] = display
        if not refine:
            return product_for_recall

        boq_row = product.get("_boq_row")
        if not isinstance(boq_row, dict):
            return product_for_recall
        section = str(boq_row.get("description") or "").strip()
        if not section:
            return product_for_recall
        hint = str(product.get("description_hint") or "").strip()
        # Include BOQ section text so rematch searches with product + section evidence.
        product_for_recall["description_hint"] = (
            f"{hint}\n{section}".strip() if hint else section
        )
        return product_for_recall

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

    def _seed_candidates(self, product: dict[str, Any]) -> list[tuple[int, Any]]:
        """Prior match/suggested ids (confidence ignored — rematch re-scores)."""
        seeds: list[tuple[int, Any]] = []
        seen: set[int] = set()

        def _add(rate_id: int) -> None:
            if rate_id in seen:
                return
            seen.add(rate_id)
            seeds.append((rate_id, None))

        for key in ("db_product_id", "suggested_db_product_id"):
            raw = product.get(key)
            if raw in (None, ""):
                continue
            try:
                _add(int(raw))
            except (TypeError, ValueError):
                continue
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
            if len(seeds) >= max(_CANDIDATE_LIMIT * 2, 6):
                break
        return seeds

    def _merge_seeded_candidates(
        self,
        product: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Keep fresh DB recall first; only fill leftover slots from prior ids.

        Earlier rematch put prior seeds first and truncated to top-3, which blocked
        new Chroma hits and returned the same product/confidence after edits.
        """
        seeds = self._seed_candidates(product)
        if not seeds:
            return candidates

        seen: set[int] = set()
        merged: list[dict[str, Any]] = []

        def _confidence_value(raw: Any) -> float:
            try:
                return float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        def _append(snapshot: dict[str, Any]) -> None:
            raw = snapshot.get("id")
            if raw in (None, ""):
                return
            try:
                rate_id = int(raw)
            except (TypeError, ValueError):
                return
            if rate_id in seen:
                return
            seen.add(rate_id)
            merged.append(snapshot)

        # Fresh recall (already scored against current filled fields) wins.
        for item in candidates:
            _append(item)

        if len(merged) >= _CANDIDATE_LIMIT:
            return merged[:_CANDIDATE_LIMIT]

        seed_ids = [rate_id for rate_id, _conf in seeds]
        rate_map = {
            rate.pk: rate
            for rate in Rate_Master_Output.objects.filter(
                pk__in=seed_ids,
                database_version_id=self.database_version_id,
            )
        }
        product_only = dict(product)
        product_only["make_hint"] = None
        for rate_id, _ignored in seeds:
            if len(merged) >= _CANDIDATE_LIMIT:
                break
            rate = rate_map.get(rate_id)
            if rate is None:
                continue
            # Re-score against current UI fields — never reuse stale listed %.
            score, _breakdown = structured_match_score(product_only, rate)
            _append(_candidate_snapshot(rate, confidence=round(float(score), 2)))

        merged.sort(
            key=lambda item: _confidence_value(item.get("confidence")),
            reverse=True,
        )
        return merged[:_CANDIDATE_LIMIT]

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
        *,
        rematch: bool = False,
    ) -> dict[str, Any]:
        enriched = dict(product)
        extracted_attrs = coerce_attributes_dict(product.get("attributes"))

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
            attribute_map = {
                normalize_attribute_key(str(src)): normalize_attribute_key(str(dst))
                for src, dst in (ai_result.get("attribute_map") or {}).items()
                if str(src).strip() and str(dst).strip()
            }
            mapped_attributes = coerce_attributes_dict(ai_result.get("mapped_attributes"))
            unmapped_attributes = coerce_attributes_dict(ai_result.get("unmapped_attributes"))
            try:
                raw_confidence = ai_result.get("match_confidence")
                ai_confidence = float(raw_confidence) if raw_confidence is not None else None
            except (TypeError, ValueError):
                ai_confidence = None
            notes = str(ai_result.get("notes") or "").strip()

        # Re-score every candidate against current filled fields so listed % is honest.
        product_for_score = dict(enriched)
        product_for_score["make_hint"] = None
        rate_ids: list[int] = []
        for item in candidates:
            try:
                rate_ids.append(int(item.get("id")))
            except (TypeError, ValueError):
                continue
        if selected_id is not None and selected_id not in rate_ids:
            rate_ids.append(selected_id)
        rate_map = {
            rate.pk: rate
            for rate in Rate_Master_Output.objects.filter(
                pk__in=rate_ids,
                database_version_id=self.database_version_id,
            )
        }
        if selected_id is not None and selected_id not in rate_map:
            selected_id = None

        rescored: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for item in candidates:
            try:
                cid = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            rate_row = rate_map.get(cid)
            if rate_row is None or cid in seen_ids:
                continue
            seen_ids.add(cid)
            structured, _ = structured_match_score(product_for_score, rate_row)
            refreshed = dict(item)
            refreshed["confidence"] = round(float(structured), 2)
            rescored.append(refreshed)
        # Keep AI pick even if it ranked outside the first few after re-score.
        if selected_id is not None and selected_id not in seen_ids:
            rate_row = rate_map.get(selected_id)
            if rate_row is not None:
                structured, _ = structured_match_score(product_for_score, rate_row)
                rescored.append(
                    _candidate_snapshot(rate_row, confidence=round(float(structured), 2))
                )
                seen_ids.add(selected_id)

        rescored.sort(
            key=lambda row: float(row.get("confidence") or 0.0),
            reverse=True,
        )
        if selected_id is not None:
            head = [item for item in rescored if int(item.get("id") or 0) == selected_id]
            tail = [item for item in rescored if int(item.get("id") or 0) != selected_id]
            candidates = (head + tail)[:_CANDIDATE_LIMIT]
        else:
            candidates = rescored[:_CANDIDATE_LIMIT]
        candidate_by_id = {
            int(item["id"]): item
            for item in candidates
            if item.get("id") is not None
        }
        slim_candidates = [_slim_candidate(item) for item in candidates]
        if selected_id is not None and selected_id not in candidate_by_id:
            selected_id = None

        # Never invent a product. Prefer AI selection; otherwise pick the best
        # structured neighbor when filled fields already look plausible.
        if selected_id is None and candidates:
            top = candidates[0]
            try:
                top_structured = float(top.get("confidence") or 0.0)
            except (TypeError, ValueError):
                top_structured = 0.0
            # Rematch: accept nearest filled-field match more readily (≥20).
            auto_floor = 20.0 if rematch else float(MATCH_CONFIDENCE_THRESHOLD)
            if top_structured >= auto_floor:
                selected_id = int(top["id"])
            else:
                top_rate = rate_map.get(int(top["id"])) if top.get("id") is not None else None
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
        # Rematch keeps expert-filled values; only fill blanks from Rate_Master.
        # Candidate Select still prefers DB values via apply_selected_candidate.
        attributes = _schema_attributes_from_rate(
            schema_keys=schema_keys,
            rate_attrs=parse_attributes(rate.Attribute),
            existing_attrs=attributes,
            prefer_rate=False,
        )
        confidence = _compute_match_confidence(
            enriched,
            rate,
            mapped_attributes=attributes,
            schema_keys=schema_keys,
            ai_confidence=ai_confidence,
            prefer_filled_fields=bool(rematch),
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
            provisional = self._provisional_schema_match(
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
                notes=notes or "Suggested DB product — fill missing attributes, then Re-analyse to rematch.",
                ai_confidence=ai_confidence,
            )
            if rematch:
                return _restore_expert_identity(provisional, product)
            return provisional

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
        # Matched products are no longer hollow slot placeholders.
        enriched["needs_extraction_review"] = False
        enriched["slot_fallback"] = False
        enriched["ai_mapping"] = {
            "selected_id": rate.pk,
            "selected_rate_master_id": rate.pk,
            "attribute_map": attribute_map,
            "notes": notes,
            "ai_confidence": ai_confidence,
            "candidate_ids": [item["id"] for item in candidates],
            "match_status": DB_MATCH_MATCHED,
            "selection_source": "rematch" if rematch else "ai",
        }
        # Initial Analyse fills blanks/core from Rate_Master. Rematch keeps the
        # expert inputs used for search; DB identity stays on match + candidates.
        # Score candidates against pre-align extract/expert fields so copying
        # Rate_Master identity cannot mint a 100% match.
        score_against = {
            key: enriched.get(key)
            for key in (
                "description_hint",
                "category",
                "sub_category",
                "class",
                "size",
                "unit",
                "capacity",
                "attributes",
            )
        }
        aligned = align_product_taxonomy_from_rate(
            enriched,
            rate,
            overwrite_core_fields=not rematch,
        )
        if rematch:
            aligned = _restore_expert_identity(aligned, product)
            score_against = {
                key: product.get(key)
                for key in score_against
            }
        return self._finalize_candidate_scores(
            aligned,
            rate,
            score_against=score_against,
        )

    def _finalize_candidate_scores(
        self,
        product: dict[str, Any],
        selected_rate: Rate_Master_Output | None = None,
        *,
        score_against: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Re-score listed candidates against extract/expert fields.

        Do not score the Rate_Master-overwritten identity against the same row —
        that always looks like 100% even when the BOQ product is unrelated.
        """
        candidates = list(product.get("db_candidates") or [])
        if not candidates:
            return product
        rate_ids: list[int] = []
        for item in candidates:
            try:
                rate_ids.append(int(item.get("id")))
            except (TypeError, ValueError):
                continue
        rate_map = {
            rate.pk: rate
            for rate in Rate_Master_Output.objects.filter(
                pk__in=rate_ids,
                database_version_id=self.database_version_id,
            )
        }
        product_only = dict(score_against or product)
        product_only["description_hint"] = product.get("description_hint")
        product_only["make_hint"] = None
        selected_id = product.get("db_product_id") or product.get("suggested_db_product_id")
        refreshed: list[dict[str, Any]] = []
        for item in candidates:
            try:
                cid = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            rate = rate_map.get(cid)
            if rate is None:
                refreshed.append(dict(item))
                continue
            score, _ = structured_match_score(product_only, rate)
            updated = dict(item)
            updated["confidence"] = round(float(score), 2)
            refreshed.append(updated)
        refreshed.sort(
            key=lambda row: float(row.get("confidence") or 0.0),
            reverse=True,
        )
        if selected_id is not None:
            try:
                selected_pk = int(selected_id)
            except (TypeError, ValueError):
                selected_pk = None
            if selected_pk is not None:
                head = [
                    item
                    for item in refreshed
                    if int(item.get("id") or 0) == selected_pk
                ]
                tail = [
                    item
                    for item in refreshed
                    if int(item.get("id") or 0) != selected_pk
                ]
                refreshed = (head + tail)[:_CANDIDATE_LIMIT]
            else:
                refreshed = refreshed[:_CANDIDATE_LIMIT]
        else:
            refreshed = refreshed[:_CANDIDATE_LIMIT]

        rate = selected_rate
        if rate is None and selected_id is not None:
            try:
                rate = rate_map.get(int(selected_id))
            except (TypeError, ValueError):
                rate = None
        if rate is not None and selected_id is not None:
            confidence = _compute_match_confidence(
                product_only,
                rate,
                mapped_attributes=coerce_attributes_dict(product.get("attributes")),
                schema_keys=list(product.get("attribute_schema") or []),
                ai_confidence=(product.get("ai_mapping") or {}).get("ai_confidence"),
                prefer_filled_fields=str(
                    (product.get("ai_mapping") or {}).get("selection_source") or ""
                )
                == "rematch",
            )
            try:
                selected_pk = int(selected_id)
            except (TypeError, ValueError):
                selected_pk = None
            if selected_pk is not None:
                for item in refreshed:
                    try:
                        if int(item.get("id") or 0) == selected_pk:
                            item["confidence"] = confidence
                            break
                    except (TypeError, ValueError):
                        continue
            product["db_match_confidence"] = confidence
            product["attribute_confidence"] = confidence
            product = _downgrade_unrelated_auto_match(product, confidence)
        product["db_candidates"] = refreshed
        return product

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
    def _extracted_payload(product: dict[str, Any], *, rematch: bool = False) -> dict[str, Any]:
        attributes = coerce_attributes_dict(product.get("attributes"))
        # Drop empty blanks so AI focuses on expert-filled values.
        filled_attributes = {
            key: value
            for key, value in attributes.items()
            if _is_filled(value)
        }
        payload: dict[str, Any] = {
            "description_hint": product.get("description_hint"),
            "category": product.get("category"),
            "sub_category": product.get("sub_category"),
            "class": product.get("class"),
            "size": product.get("size"),
            "unit": product.get("unit"),
            "capacity": product.get("capacity"),
            # Analysis does not select make; omit hints so AI maps product only.
            "make_hint": None,
            "attributes": filled_attributes,
        }
        if rematch:
            payload["rematch"] = True
            prior = product.get("_prior_match")
            if not isinstance(prior, dict):
                prior = {
                    "status": product.get("db_match_status"),
                    "db_product_id": product.get("db_product_id")
                    or product.get("suggested_db_product_id"),
                    "catalog_product_id": product.get("catalog_product_id")
                    or product.get("suggested_catalog_product_id"),
                    "tech_key": product.get("db_product_tech_key"),
                    "summary": product.get("db_product_summary"),
                    "confidence": product.get("db_match_confidence"),
                }
            payload["prior_match"] = prior
            payload["expert_filled_attributes"] = filled_attributes
            boq_row = product.get("_boq_row")
            if isinstance(boq_row, dict) and (
                boq_row.get("description") or boq_row.get("row_id")
            ):
                payload["boq_row"] = {
                    "row_id": boq_row.get("row_id"),
                    "description": boq_row.get("description") or "",
                    "serial": boq_row.get("serial") or "",
                }
        return payload

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
            fill_blanks_only=True,
        )

    def _attach_catalog_product_id(self, product: dict[str, Any]) -> dict[str, Any]:
        """Resolve Product_Helper Product_ID for Make & Vendor / Labour joins."""
        from apps.boq.services.product_helper_matching_service import (
            ProductHelperMatchingService,
        )

        enriched = dict(product)
        helper_service = ProductHelperMatchingService(self.database_version_id)

        # Prefer Product_ID from the confirmed Rate_Master_Output row.
        rate_pk = enriched.get("db_product_id")
        if rate_pk not in (None, ""):
            try:
                rate = Rate_Master_Output.objects.filter(
                    pk=int(rate_pk),
                    database_version_id=self.database_version_id,
                ).first()
            except (TypeError, ValueError):
                rate = None
            if rate and str(rate.Product_ID or "").strip():
                helper = helper_service.get_by_product_id(str(rate.Product_ID).strip())
                if helper is not None:
                    enriched["catalog_product_id"] = helper.Product_ID
                    enriched["product_helper_id"] = helper.pk
                    enriched["catalog_match_confidence"] = float(
                        enriched.get("db_match_confidence") or 100.0
                    )
                    return enriched
                enriched["catalog_product_id"] = str(rate.Product_ID).strip()
                return enriched

        # Fall back to structured Product_Helper match from BOQ taxonomy.
        match = helper_service.match_product(enriched)
        best = match.get("best") or {}
        product_id = str(best.get("product_id") or "").strip()
        if product_id and float(match.get("confidence") or 0) >= MATCH_CONFIDENCE_THRESHOLD:
            enriched["catalog_product_id"] = product_id
            enriched["product_helper_id"] = best.get("product_helper_id")
            enriched["catalog_match_confidence"] = match.get("confidence")
        elif product_id:
            # Keep a suggested Product_ID for Find in DB without claiming a match.
            enriched["suggested_catalog_product_id"] = product_id
            enriched["catalog_match_confidence"] = match.get("confidence")
        return enriched
