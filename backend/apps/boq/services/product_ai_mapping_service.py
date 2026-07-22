"""AI layer: map extracted products to Rate_Master rows and attribute schemas."""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from ai.context import align_product_taxonomy_from_db_labels, align_product_taxonomy_from_rate
from ai.service import AIService
from apps.boq.services.product_matching_service import (
    ProductMatchingService,
    structured_match_score,
)
from apps.database_manager.models import Rate_Master
from common.constants import MATCH_CONFIDENCE_THRESHOLD
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

_BATCH_SIZE = 4
_CANDIDATE_LIMIT = 10

DB_MATCH_MATCHED = "matched"
DB_MATCH_PROVISIONAL = "provisional"
DB_MATCH_UNMATCHED = "unmatched"


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
        "tech_key": snapshot.get("tech_key"),
        "category": snapshot.get("category"),
        "sub_category": snapshot.get("sub_category"),
        "class": snapshot.get("class"),
        "size": _json_scalar(snapshot.get("size")),
        "unit": snapshot.get("unit"),
        "capacity": _json_scalar(snapshot.get("capacity")),
        "make": snapshot.get("make"),
        "attribute_schema": list(snapshot.get("attribute_schema") or []),
        "attributes": dict(snapshot.get("attributes") or {}),
        "confidence": _json_scalar(snapshot.get("confidence")),
        "summary": _product_summary(snapshot),
    }


def _candidate_snapshot(rate: Rate_Master, *, confidence: float | None = None) -> dict[str, Any]:
    """Serialize a Rate_Master row for AI/mapping.

    ``id`` / ``rate_master_id`` are both ``Rate_Master.id`` (Django PK). There is
    no ``rate_master_id`` column on the table — that name is only a JSON alias.
    """
    attrs = parse_attributes(rate.Attribute)
    return {
        "id": rate.pk,
        "rate_master_id": rate.pk,  # alias of id for older callers
        "tech_key": rate.Tech_Key,
        "category": rate.Category,
        "sub_category": rate.Sub_Category,
        "class": rate.Class,
        "size": _json_scalar(rate.Size),
        "unit": rate.Unit,
        "capacity": _json_scalar(rate.Capacity),
        "make": rate.Make,
        "attribute_schema": list(attrs.keys()),
        "attributes": attrs,
        "confidence": confidence,
    }


def _product_summary(snapshot: dict[str, Any]) -> str:
    parts = [
        snapshot.get("category"),
        snapshot.get("sub_category"),
        snapshot.get("class"),
        snapshot.get("size"),
        snapshot.get("make"),
    ]
    return " / ".join(str(part).strip() for part in parts if _is_filled(part)) or "Matched product"


def _normalize_attr_dict(raw: Any) -> dict[str, str]:
    return coerce_attributes_dict(raw)


def _compute_match_confidence(
    extracted: dict[str, Any],
    rate: Rate_Master,
    *,
    mapped_attributes: dict[str, str],
    schema_keys: list[str],
    ai_confidence: float | None,
) -> float:
    """Blend structured field score with attribute mapping fill (service-side)."""
    structured, _breakdown = structured_match_score(extracted, rate)
    attr_score = compute_attribute_confidence(
        schema_keys,
        mapped_attributes,
        db_attrs=parse_attributes(rate.Attribute) or None,
    )
    if schema_keys:
        blended = (0.55 * structured) + (0.45 * attr_score)
    else:
        blended = structured
    if ai_confidence is not None:
        blended = (0.7 * blended) + (0.3 * float(ai_confidence))
    return round(max(0.0, min(100.0, blended)), 2)


def _map_attrs_onto_schema(
    *,
    schema_keys: list[str],
    extracted_attrs: dict[str, str],
    attribute_map: dict[str, str],
    mapped_attributes: dict[str, str],
    unmapped_attributes: dict[str, str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Resolve AI + extracted attributes onto a Rate_Master Attribute schema."""
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
    Retrieve Rate_Master candidates, then use AI to select the product and map
    extracted attributes onto the DB Attribute schema for Analysis review.

    Never invents Rate_Master rows or Tech_Key values. Attaches a DB product only
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

    def map_products(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not products:
            return []

        prepared: list[dict[str, Any]] = []
        for index, product in enumerate(products):
            candidates = self._recall_candidates(product)
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
        progress_callback=None,
    ) -> list[dict[str, Any]]:
        from .product_attribute_enrichment_service import product_needs_attribute_enrichment

        pending: list[tuple[int, int, dict[str, Any]]] = []
        for row_index, row in enumerate(rows):
            for product_index, product in enumerate(row.get("products") or []):
                if only_missing and not product_needs_attribute_enrichment(product):
                    continue
                pending.append((row_index, product_index, product))

        if not pending:
            if progress_callback:
                progress_callback(1, 1)
            return rows

        # Map in small chunks so progress can advance during long enrichments.
        chunk_size = max(_BATCH_SIZE, 4)
        mapped_products: list[dict[str, Any]] = []
        total = len(pending)
        if progress_callback:
            progress_callback(0, total)
        for start in range(0, total, chunk_size):
            chunk = pending[start : start + chunk_size]
            mapped_products.extend(self.map_products([item[2] for item in chunk]))
            if progress_callback:
                progress_callback(min(total, start + len(chunk)), total)

        updated_rows = [dict(row) for row in rows]
        for (row_index, product_index, _product), mapped in zip(pending, mapped_products, strict=False):
            products = list(updated_rows[row_index].get("products") or [])
            products[product_index] = mapped
            updated_rows[row_index] = {**updated_rows[row_index], "products": products}
        return updated_rows

    def rematch_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Re-run DB candidate recall + AI mapping using current product fields/attrs."""
        return self.map_rows(rows, only_missing=False)

    def _recall_candidates(self, product: dict[str, Any]) -> list[dict[str, Any]]:
        match = self._matcher.match_product(product, chroma_limit=25)
        snapshots: list[dict[str, Any]] = []
        seen: set[int] = set()

        for item in match.get("candidates") or []:
            rate_id = item.get("rate_master_id")
            if rate_id in seen:
                continue
            rate = Rate_Master.objects.filter(
                pk=rate_id,
                database_version_id=self.database_version_id,
            ).first()
            if rate is None:
                continue
            seen.add(int(rate_id))
            snapshots.append(
                _candidate_snapshot(rate, confidence=item.get("confidence"))
            )
            if len(snapshots) >= _CANDIDATE_LIMIT:
                break

        if snapshots:
            return snapshots

        # SQL-only path when Chroma returns nothing.
        for item in self._matcher._sql_fallback_candidates(product)[:_CANDIDATE_LIMIT]:
            rate = item.get("rate")
            if rate is None:
                continue
            snapshots.append(
                _candidate_snapshot(rate, confidence=item.get("confidence"))
            )
        return snapshots

    def _run_ai_batches(self, prepared: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Call map_product_match with ``{{PRODUCTS_PAYLOAD}}`` filled from recall.

        PRODUCTS_PAYLOAD is built here (not loaded from a file): a JSON list of
        ``{product_ref, extracted, candidates[]}`` for the current batch.
        Each candidate ``id`` is ``Rate_Master.id`` (table PK).
        """
        template = AIService.load_prompt("map_product_match.txt")
        by_ref: dict[str, dict[str, Any]] = {}
        for start in range(0, len(prepared), _BATCH_SIZE):
            batch = prepared[start : start + _BATCH_SIZE]
            payload = [
                {
                    "product_ref": item["product_ref"],
                    "extracted": item["extracted"],
                    "candidates": [
                        {
                            "id": candidate["id"],
                            "tech_key": candidate.get("tech_key"),
                            "category": candidate.get("category"),
                            "sub_category": candidate.get("sub_category"),
                            "class": candidate.get("class"),
                            "size": candidate.get("size"),
                            "unit": candidate.get("unit"),
                            "capacity": candidate.get("capacity"),
                            "make": candidate.get("make"),
                            "attribute_schema": candidate.get("attribute_schema") or [],
                            "attributes": candidate.get("attributes") or {},
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
            top_rate = Rate_Master.objects.filter(
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
                notes=notes or "No Rate_Master candidate selected.",
            )

        snapshot = candidate_by_id.get(selected_id)
        rate = Rate_Master.objects.filter(
            pk=selected_id,
            database_version_id=self.database_version_id,
        ).first()
        if rate is None:
            return self._fallback_without_match(
                enriched,
                extracted_attrs,
                candidates=slim_candidates,
                notes="Selected Rate_Master row not found.",
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

        attributes = {**mapped_attributes, **unmapped_attributes}
        confidence = _compute_match_confidence(
            enriched,
            rate,
            mapped_attributes=mapped_attributes,
            schema_keys=schema_keys,
            ai_confidence=ai_confidence,
        )
        summary_source = snapshot or _candidate_snapshot(rate, confidence=confidence)
        missing_keys = _missing_attribute_keys(schema_keys, attributes)

        # Confirm only when blended confidence clears the threshold — never stamp
        # Tech_Key from a weak / unrelated candidate.
        if confidence < MATCH_CONFIDENCE_THRESHOLD:
            return self._provisional_schema_match(
                enriched,
                rate=rate,
                snapshot=summary_source,
                schema_keys=schema_keys,
                attributes=attributes,
                mapped_attributes=mapped_attributes,
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
        enriched["db_product_make"] = rate.Make
        enriched["db_product_tech_key"] = rate.Tech_Key
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
        return align_product_taxonomy_from_rate(enriched, rate)

    def _provisional_schema_match(
        self,
        product: dict[str, Any],
        *,
        rate: Rate_Master,
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
        enriched["db_candidates"] = [_slim_candidate(item) for item in candidates]
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
        return align_product_taxonomy_from_rate(enriched, rate)

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
            "make_hint": product.get("make_hint"),
            "attributes": product.get("attributes") or {},
        }

    @staticmethod
    def _fallback_without_match(
        product: dict[str, Any],
        extracted_attrs: dict[str, str] | None = None,
        *,
        candidates: list[dict[str, Any]] | None = None,
        notes: str = "No Rate_Master candidate selected.",
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
                attrs = {**merged}
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
