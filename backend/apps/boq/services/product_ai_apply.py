"""AI batch mapping + confidence finalization for Product AI mapping."""
from __future__ import annotations

import json
import logging
from typing import Any

from ai.context import (
    align_product_taxonomy_from_db_labels,
    align_product_taxonomy_from_rate,
)
from ai.service import AIService
from apps.boq.services.product_ai_common import (
    DB_MATCH_MATCHED,
    DB_MATCH_PROVISIONAL,
    DB_MATCH_UNMATCHED,
    _CANDIDATE_LIMIT,
    _candidate_snapshot,
    _clear_weak_match_inputs,
    _compute_match_confidence,
    _downgrade_unrelated_auto_match,
    _is_filled,
    _map_attrs_onto_schema,
    _mapping_batch_size,
    _missing_attribute_keys,
    _normalize_text_key,
    _prefer_candidate_first,
    _product_summary,
    _restore_expert_identity,
    _schema_attributes_from_rate,
    _should_blank_weak_match_inputs,
    _slim_candidate,
)
from apps.boq.services.product_matching_service import structured_match_score
from apps.database_manager.models import Rate_Master_Output
from common.constants import (
    ANALYSIS_INPUT_FILL_CONFIDENCE,
    MATCH_CONFIDENCE_THRESHOLD,
)
from utils.attribute_parser import (
    coerce_attributes_dict,
    normalize_attribute_key,
    parse_attributes,
)
from utils.product_synonyms import format_synonym_map_for_ai

from .product_attribute_enrichment_service import (
    compute_attribute_confidence,
    merge_attributes_onto_schema,
)

logger = logging.getLogger("boq_ai")


class ProductAIApplyMixin:
    """Run map_product_match batches and apply / finalize AI selections."""

    # Provided by ProductAIMappingService.__init__.
    database_version_id: int
    _ai: AIService

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
            def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, int]:
                try:
                    conf = -float(candidate.get("confidence") or 0)
                except (TypeError, ValueError):
                    conf = 0.0
                try:
                    cid = int(candidate.get("id") or 0)
                except (TypeError, ValueError):
                    cid = 0
                return (conf, cid)

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
                        for candidate in sorted(item["candidates"], key=_candidate_sort_key)
                    ],
                }
                for item in batch
                if item["candidates"]
            ]
            if not payload:
                continue
            prompt = template.replace(
                "{{SYNONYM_MAP}}",
                format_synonym_map_for_ai(),
            ).replace(
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
        blank_weak_inputs: bool = True,
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
            raw_id = item.get("id")
            if raw_id is None:
                continue
            try:
                rate_ids.append(int(raw_id))
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
            raw_id = item.get("id")
            if raw_id is None:
                continue
            try:
                cid = int(raw_id)
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
                blank_weak_inputs=blank_weak_inputs,
            )
            if rematch:
                return _restore_expert_identity(provisional, product)
            if blank_weak_inputs and _should_blank_weak_match_inputs(
                provisional, confidence=confidence, rematch=False
            ):
                return _clear_weak_match_inputs(provisional)
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
        # Initial Analyse fills blanks/core from Rate_Master when confidence is
        # strong enough for the UI. Also promote Rate-aligned identity when the
        # product already cleared the match floor but sat below the fill gate
        # (e.g. hose box ~40% from Size=0 noise → align → ~100% like Re-analyse).
        fill_inputs = (
            not rematch
            and float(confidence or 0.0) >= float(ANALYSIS_INPUT_FILL_CONFIDENCE)
        )
        promote_identity = (
            not rematch
            and not fill_inputs
            and float(confidence or 0.0) >= float(MATCH_CONFIDENCE_THRESHOLD)
        )
        aligned = align_product_taxonomy_from_rate(
            enriched,
            rate,
            overwrite_core_fields=bool(fill_inputs or promote_identity),
        )
        if rematch:
            aligned = _restore_expert_identity(aligned, product)
            score_against = {
                key: product.get(key)
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
        elif fill_inputs or promote_identity:
            # Analysis shows Rate_Master-filled fields — score that identity so
            # correct fills are not stuck at ~40% / ~90–92% from pre-align wording.
            confidence = _compute_match_confidence(
                aligned,
                rate,
                mapped_attributes=coerce_attributes_dict(aligned.get("attributes")),
                schema_keys=schema_keys,
                ai_confidence=ai_confidence,
                prefer_filled_fields=True,
                # Hose-box style: promote Rate-aligned Analyse identity to 100%.
                # Never use this on Re-analyse (that forced every rematch to 100%).
                promote_identity_ceiling=True,
            )
            aligned["db_match_confidence"] = confidence
            aligned["attribute_confidence"] = confidence
            for item in slim_candidates:
                try:
                    if int(item.get("id") or 0) == int(rate.pk):
                        item["confidence"] = confidence
                        break
                except (TypeError, ValueError):
                    continue
            aligned["db_candidates"] = slim_candidates
            score_against = aligned
        else:
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
        finalized = self._finalize_candidate_scores(
            aligned,
            rate,
            score_against=score_against,
        )
        if blank_weak_inputs and _should_blank_weak_match_inputs(
            finalized,
            confidence=float(finalized.get("db_match_confidence") or confidence),
            rematch=rematch,
        ):
            return _clear_weak_match_inputs(finalized)
        return finalized


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
            selection_source = str(
                (product.get("ai_mapping") or {}).get("selection_source") or ""
            )
            confidence = _compute_match_confidence(
                product_only,
                rate,
                mapped_attributes=coerce_attributes_dict(product.get("attributes")),
                schema_keys=list(product.get("attribute_schema") or []),
                ai_confidence=(product.get("ai_mapping") or {}).get("ai_confidence"),
                prefer_filled_fields=selection_source
                in {"rematch", "expert", "expert_confirm", "ai"},
            )
            try:
                prior = float(product.get("db_match_confidence") or 0.0)
            except (TypeError, ValueError):
                prior = 0.0
            # Do not drag a just-filled Analyse / Confirm score back down.
            if prior >= 99.5 and confidence < prior:
                confidence = prior
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
        blank_weak_inputs: bool = True,
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
        aligned = align_product_taxonomy_from_rate(
            enriched, rate, overwrite_core_fields=False
        )
        if blank_weak_inputs and _should_blank_weak_match_inputs(
            aligned, confidence=confidence, rematch=False
        ):
            return _clear_weak_match_inputs(aligned)
        return aligned


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
        # Full section is context for meaning; product identity is the fields above
        # (+ slot line). Send on Analyse and Re-analyse whenever attached.
        boq_row = product.get("_boq_row")
        if isinstance(boq_row, dict) and (
            boq_row.get("description") or boq_row.get("row_id")
        ):
            payload["boq_row"] = {
                "row_id": boq_row.get("row_id"),
                "description": boq_row.get("description") or "",
                "slot_description": boq_row.get("slot_description") or "",
                "serial": boq_row.get("serial") or "",
                "role": "section_context",
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
            payload["expert_filled_fields"] = {
                key: product.get(key)
                for key in (
                    "description_hint",
                    "category",
                    "sub_category",
                    "class",
                    "size",
                    "unit",
                    "capacity",
                )
                if _is_filled(product.get(key))
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
                return ProductAIApplyMixin._provisional_from_candidate(
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

