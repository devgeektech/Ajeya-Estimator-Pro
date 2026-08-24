"""Orchestrate BOQ extraction, matching, and analysis persistence."""
from __future__ import annotations

import logging
from typing import Any

from common.db import atomic

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_store import (
    analysis_json_relative_path,
    save_boq_analysis_json,
)
from apps.boq.services.boq_extraction_service import (
    BOQExtractionService,
    normalize_product_fields,
    rehydrate_analysis_rows_quantity,
)
from apps.boq.services.boq_extract_service import load_extract_data
from apps.boq.services.boq_job_progress import (
    set_boq_job_progress,
)
from apps.boq.services.boq_row_fields import DESCRIPTION_KEYS
from apps.boq.services.boq_row_grouping_service import full_description_for_row, resolve_anchor_row_id
from apps.boq.services.make_list_constraint_service import walk_rows_tree
from apps.boq.services.product_ai_mapping_service import ProductAIMappingService
from apps.boq.services.product_attribute_enrichment_service import product_needs_attribute_enrichment
from apps.boq.services.serial_normalizer import structure_for_analysis
from apps.database_manager.services.activation import get_active_database_version
from common.choices import BOQStatus
from common.constants import ANALYSIS_INPUT_FILL_CONFIDENCE
from common.exceptions import AIServiceError, BOQAIError, ValidationError
from utils.json_safe import json_safe

logger = logging.getLogger("boq_ai")

PHASE_EXTRACTED = "extracted"


def _database_snapshot(version) -> dict[str, Any]:
    """Stable id + display name for the master DB used by a BOQ job."""
    if version is None:
        return {"database_version_id": None, "database_name": ""}
    name = (
        str(getattr(version, "name", "") or "").strip()
        or str(getattr(version, "source_filename", "") or "").strip()
        or f"DB v{getattr(version, 'version_number', '')}".strip()
    )
    return {
        "database_version_id": int(version.pk),
        "database_name": name,
    }


def _upload_basename(field) -> str:
    if not field:
        return ""
    name = str(getattr(field, "name", "") or "")
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _row_description(boq_data: dict, row_id: str) -> str:
    full_text = full_description_for_row(boq_data, row_id)
    if full_text:
        return full_text
    tree = boq_data.get("rows_tree") or []
    for node in walk_rows_tree(tree):
        if node.get("row_id") != row_id:
            continue
        fields = node.get("fields") or {}
        for key in DESCRIPTION_KEYS:
            value = fields.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return ""


def _row_order(boq_payload: dict, extraction: dict) -> list[str]:
    row_order = [
        str(row.get("row_id"))
        for row in (boq_payload.get("rows") or [])
        if row.get("row_id")
    ]
    if row_order:
        return row_order
    return [
        str(row.get("row_id"))
        for row in extraction.get("rows") or []
        if row.get("row_id")
    ]


def _compute_extraction_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "rows_total": 0,
        "rows_skipped": 0,
        "products_total": 0,
        "activities_total": 0,
    }
    for row in rows:
        row["activities"] = []
        stats["rows_total"] += 1
        if row.get("skip_matching"):
            stats["rows_skipped"] += 1
        stats["products_total"] += len(row.get("products") or [])
    return stats


def _replace_rows(
    existing_rows: list[dict[str, Any]],
    replacements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    replacement_map = {
        str(row.get("row_id")): row for row in replacements if row.get("row_id")
    }
    updated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in existing_rows:
        row_id = str(row.get("row_id") or "")
        if row_id in replacement_map:
            updated.append(replacement_map[row_id])
            seen.add(row_id)
        else:
            updated.append(row)
    for row_id, row in replacement_map.items():
        if row_id not in seen:
            updated.append(row)
    return updated


class BOQAnalysisService:
    """Run BOQ extraction and persist analysis_data."""

    def __init__(self, boq_id: int):
        self.boq_id = boq_id

    def run_extraction(self) -> dict[str, Any]:
        """Extract products, then enrich attributes from Rate_Master."""
        boq = self._get_boq()
        self._set_status(boq, BOQStatus.PROCESSING)
        # Start at 1% — do not jump ahead until extract/match units complete.
        set_boq_job_progress(boq.pk, percent=1, label="Starting analysis...", phase="extract")

        # Pin active DB for this job so concurrent analyses stay on one version.
        active_version = get_active_database_version()
        db_snap = _database_snapshot(active_version)
        logger.info(
            "BOQ extraction start id=%s name=%s boq_file=%s make_list=%s "
            "database_version_id=%s database_name=%s",
            boq.pk,
            boq.boq_name,
            _upload_basename(boq.uploaded_file),
            _upload_basename(boq.make_list_file),
            db_snap.get("database_version_id"),
            db_snap.get("database_name") or "(none)",
        )

        try:
            # Always load this BOQ's own PostgreSQL / upload payloads (never shared).
            set_boq_job_progress(boq.pk, percent=2, label="Loading BOQ data...", phase="extract")
            boq_payload, make_list_payload = load_extract_data(boq)
            logger.info(
                "BOQ extraction inputs id=%s boq_rows=%s make_list_rows=%s",
                boq.pk,
                len((boq_payload or {}).get("rows") or []),
                len((make_list_payload or {}).get("rows") or []),
            )
            boq_data = structure_for_analysis(boq_payload)
            set_boq_job_progress(boq.pk, percent=3, label="Extracting products...", phase="extract")

            def _on_extract_progress(done: int, total: int) -> None:
                total = max(total, 1)
                # Extraction covers roughly 3% → 55% as batches finish.
                percent = 3 + int((done / total) * 52)
                label = (
                    "Extracting products..."
                    if done <= 0
                    else f"Extracting products ({done}/{total})..."
                )
                logger.info(
                    "BOQ extraction progress id=%s sections=%s/%s percent=%s",
                    boq.pk,
                    done,
                    total,
                    percent,
                )
                set_boq_job_progress(
                    boq.pk,
                    percent=percent,
                    label=label,
                    phase="extract",
                )

            extraction = BOQExtractionService(boq_data).extract(
                progress_callback=_on_extract_progress,
            )
            extraction_by_row = {
                str(row.get("row_id")): row
                for row in extraction.get("rows") or []
                if row.get("row_id")
            }

            extracted_rows: list[dict[str, Any]] = []
            for row_id in _row_order(boq_payload, extraction):
                row = extraction_by_row.get(row_id)
                if not row:
                    continue
                extracted_rows.append({**row, "product_matches": []})

            set_boq_job_progress(
                boq.pk,
                percent=55,
                label="Matching products to database...",
                phase="extract",
            )

            def _on_enrich_progress(done: int, total: int) -> None:
                total = max(int(total or 0), 1)
                done = max(0, min(int(done or 0), total))
                # Matching covers roughly 55% → 95% (leave headroom for save/complete).
                percent = min(95, 55 + int((done / total) * 40))
                logger.info(
                    "BOQ matching progress id=%s products=%s/%s percent=%s",
                    boq.pk,
                    done,
                    total,
                    percent,
                )
                set_boq_job_progress(
                    boq.pk,
                    percent=percent,
                    label=f"Matching products to database ({done}/{total})...",
                    phase="extract",
                )

            # Attach full section as AI context; slot line drives product identity.
            # Do not fold the whole section into Chroma query text (hydrant titles
            # were drowning pipe/valve slots).
            for row in extracted_rows:
                row_id = str(row.get("row_id") or "")
                section_text = _row_description(boq_data, row_id) if row_id else ""
                if section_text:
                    row["description"] = section_text
                for product in row.get("products") or []:
                    if not isinstance(product, dict):
                        continue
                    slot_id = str(
                        product.get("qty_row_id") or product.get("source_row_id") or ""
                    ).strip()
                    slot_text = ""
                    if slot_id and slot_id != row_id:
                        slot_text = _row_description(boq_data, slot_id)
                    elif slot_id and slot_id == row_id:
                        # Single-line section: description_hint / product owns identity.
                        slot_text = str(product.get("description_hint") or "").strip()
                    if section_text or slot_text:
                        product["_boq_row"] = {
                            "row_id": row_id,
                            "description": section_text,
                            "slot_description": slot_text,
                            "serial": str(row.get("serial") or row.get("ser_no") or ""),
                        }

            extracted_rows = self._enrich_extracted_attributes(
                extracted_rows,
                database_version_id=db_snap.get("database_version_id"),
                progress_callback=_on_enrich_progress,
            )
            # Mapping must not leave blank quantities when BOQ slots are known.
            extracted_rows = rehydrate_analysis_rows_quantity(boq_data, extracted_rows)

            set_boq_job_progress(boq.pk, percent=98, label="Saving results...", phase="extract")
            analysis_payload = {
                "schema_version": 2,
                "phase": PHASE_EXTRACTED,
                "boq_id": boq.pk,
                "boq_name": boq.boq_name,
                **db_snap,
                "stats": _compute_extraction_stats(extracted_rows),
                "extraction": {
                    "schema_version": extraction.get("schema_version"),
                    "row_count": extraction.get("row_count"),
                },
                "rows": extracted_rows,
                # Locked until Analysis → Next runs lowest-price prefills.
                "make_vendor_defaults_applied": False,
                "subcategory_make_selections": {},
            }
            self._persist_analysis(boq, analysis_payload, BOQStatus.EXTRACTED)
            set_boq_job_progress(boq.pk, percent=100, label="Analysis complete", phase="extract")
            logger.info(
                "BOQ extraction completed for id=%s (%s) database=%s",
                boq.pk,
                boq.boq_name,
                db_snap.get("database_name") or db_snap.get("database_version_id"),
            )
            self._audit(boq, "Analysed BOQ")
            self._notify_user(
                boq,
                "BOQ analysed",
                f"BOQ '{boq.boq_name}' analysis finished. Review products on the Analysis tab.",
            )
            return analysis_payload
        except Exception as exc:
            logger.exception("BOQ extraction failed for id=%s", boq.pk)
            # Status first so polls never see PROCESSING + terminal 100%.
            self._set_status(boq, BOQStatus.ANALYSIS_FAILED)
            set_boq_job_progress(boq.pk, percent=100, label="Analysis failed", phase="extract")
            self._audit(boq, "Analysis failed")
            self._notify_user(
                boq,
                "BOQ analysis failed",
                f"BOQ '{boq.boq_name}' analysis failed. Open the BOQ to retry.",
            )
            if isinstance(exc, (AIServiceError, BOQAIError)):
                raise
            raise BOQAIError(f"BOQ extraction failed: {exc}") from exc

    @staticmethod
    def _status_after_row_work(previous_status: str) -> str:
        """Keep pipeline stage after rematch/re-extract; only clear in-flight job statuses."""
        if previous_status in {
            BOQStatus.PROCESSING,
            BOQStatus.MATCHING,
            BOQStatus.ANALYSIS_FAILED,
        }:
            return BOQStatus.EXTRACTED
        if previous_status in {
            BOQStatus.EXTRACTED,
            BOQStatus.MAKE_VENDOR,
            BOQStatus.LABOUR,
            BOQStatus.PROCESSED,
            BOQStatus.READY_EXPORT,
            BOQStatus.EXPORTED,
        }:
            return previous_status
        return BOQStatus.EXTRACTED

    def rematch_row(
        self,
        row_id: str,
        product_index: int | None = None,
        *,
        force_reextract: bool = False,
    ) -> dict[str, Any]:
        """
        Rematch one product (or re-extract an empty section).

        Analysis product **Re-analyse** uses ``force_reextract=False`` with a
        ``product_index``: rematches that product only via
        ``ProductAIMappingService.rematch_product`` using UI fields, filled blank
        attributes, prior Product_IDs, and the BOQ row description.

        Empty-section **Re-analyse** (or ``force_reextract=True``) rebuilds products
        from the BOQ workbook via ``extract_products.txt`` (same as initial Analyse).
        """
        with atomic():
            try:
                boq = BOQ.objects.select_for_update().get(pk=self.boq_id)
            except BOQ.DoesNotExist:
                raise BOQAIError(f"BOQ id={self.boq_id} not found.") from None

            existing = dict(boq.analysis_data or {})
            rows = list(existing.get("rows") or [])
            if not rows:
                raise ValidationError("Run Analyse first to extract products from this BOQ.")
            if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
                raise ValidationError("Wait for the current job to finish.")

            target = next(
                (row for row in rows if str(row.get("row_id")) == str(row_id)),
                None,
            )
            if target is None:
                raise ValidationError(f"Unknown BOQ row: {row_id}")

            rematch_plan = None
            products = list(target.get("products") or [])
            if force_reextract or not products:
                # Release lock before long workbook re-extract.
                pass
            else:
                previous_status = boq.status
                stored_db_id = int(existing.get("database_version_id") or 0) or None
                target = dict(target)
                # Do not normalize sibling products — rematch must not rewrite
                # their Class or stored match %. Keep expert Class (including 0).
                products = [dict(product) for product in products]
                work_product_index = product_index
                if work_product_index is not None:
                    want = int(work_product_index)
                    selected = next(
                        (
                            product
                            for product in products
                            if int(product.get("product_index", -1)) == want
                        ),
                        None,
                    )
                    if selected is None:
                        raise ValidationError(f"Unknown product index: {product_index}")
                    stub_products = [
                        normalize_product_fields(selected, preserve_class=True)
                    ]
                else:
                    stub_products = [
                        normalize_product_fields(product, preserve_class=True)
                        for product in products
                    ]
                    want = None
                # Drop out of the lock before OpenAI/Chroma work.
                rematch_plan = {
                    "previous_status": previous_status,
                    "stored_db_id": stored_db_id,
                    "target": target,
                    "products": products,
                    "stub_products": stub_products,
                    "want": want,
                    "existing": existing,
                    "rows": rows,
                }

        if force_reextract or not (target.get("products") or []) or rematch_plan is None:
            return self.re_extract_row(row_id)

        previous_status = rematch_plan["previous_status"]
        stored_db_id = rematch_plan["stored_db_id"]
        target = rematch_plan["target"]
        products = rematch_plan["products"]
        stub_products = rematch_plan["stub_products"]
        want = rematch_plan["want"]
        existing = rematch_plan["existing"]
        rows = rematch_plan["rows"]

        try:
            version_id = int(stored_db_id or 0)
            if not version_id:
                active_version = get_active_database_version()
                version_id = int(active_version.pk) if active_version else 0
            if not version_id:
                raise ValidationError("No active master database. Upload a database first.")

            mapper = ProductAIMappingService(version_id)
            boq_obj = self._get_boq()

            if want is not None:
                # Product-wise Re-analyse: one product + BOQ row + UI inputs.
                source_product = stub_products[0]
                boq_payload = boq_obj.boq_data or {}
                section_text = _row_description(boq_payload, str(row_id))
                slot_id = str(
                    source_product.get("qty_row_id")
                    or source_product.get("source_row_id")
                    or ""
                ).strip()
                slot_text = ""
                if slot_id and slot_id != str(row_id):
                    slot_text = _row_description(boq_payload, slot_id)
                elif not slot_text:
                    slot_text = str(source_product.get("description_hint") or "").strip()
                # Full section for AI meaning; expert UI fields + slot line for recall.
                boq_context = {
                    "row_id": str(row_id),
                    "description": section_text,
                    "slot_description": slot_text,
                    "serial": str(target.get("serial") or target.get("ser_no") or ""),
                }
                updated_product = mapper.rematch_product(
                    source_product,
                    boq_row=boq_context,
                )
                updated_product.pop("_boq_row", None)
                updated_product.pop("_prior_match", None)
                rematched_rows = None
                rematched_product = updated_product
            else:
                stub = {**target, "products": stub_products}
                rematched = mapper.rematch_rows([stub])
                rematched_rows = rematched
                rematched_product = None

            if rematched_rows is not None:
                rematched_rows = rehydrate_analysis_rows_quantity(
                    boq_obj.boq_data or {},
                    rematched_rows,
                )

            persist_status = self._status_after_row_work(previous_status)
            with atomic():
                boq = BOQ.objects.select_for_update().get(pk=self.boq_id)
                latest = dict(boq.analysis_data or {})
                latest_rows = list(latest.get("rows") or rows)
                if rematched_product is not None and want is not None:
                    # Replace only the rematched product; leave sibling % / fields intact.
                    updated_rows = []
                    for row in latest_rows:
                        if str(row.get("row_id")) != str(row_id):
                            updated_rows.append(row)
                            continue
                        latest_products = list(row.get("products") or [])
                        merged = []
                        for product in latest_products:
                            if int(product.get("product_index", -1)) == want:
                                merged.append(rematched_product)
                            else:
                                merged.append(product)
                        updated_rows.append({**row, "products": merged})
                else:
                    updated_rows = _replace_rows(latest_rows, rematched_rows or [])
                extraction_meta = dict(latest.get("extraction") or existing.get("extraction") or {})
                extraction_meta["last_row_rematch"] = str(row_id)
                extraction_meta["last_product_rematch"] = product_index
                analysis_payload = {
                    **latest,
                    "schema_version": 2,
                    "phase": PHASE_EXTRACTED,
                    "boq_id": boq.pk,
                    "boq_name": boq.boq_name,
                    "stats": _compute_extraction_stats(updated_rows),
                    "extraction": extraction_meta,
                    "rows": updated_rows,
                }
                self._persist_analysis(boq, analysis_payload, persist_status)
            logger.info(
                "BOQ row rematch completed for id=%s row=%s product=%s",
                self.boq_id,
                row_id,
                product_index,
            )
            return analysis_payload
        except Exception as exc:
            logger.exception(
                "BOQ row rematch failed for id=%s row=%s", self.boq_id, row_id
            )
            try:
                boq = BOQ.objects.get(pk=self.boq_id)
                self._set_status(
                    boq, previous_status if previous_status else BOQStatus.ANALYSIS_FAILED
                )
            except BOQ.DoesNotExist:
                pass
            if isinstance(exc, (AIServiceError, BOQAIError, ValidationError)):
                raise
            raise BOQAIError(f"BOQ row rematch failed: {exc}") from exc

    def re_extract_row(self, row_id: str) -> dict[str, Any]:
        """Re-run AI extraction for one anchor group and merge into analysis_data."""
        boq = self._get_boq()
        existing = dict(boq.analysis_data or {})
        if not existing.get("rows"):
            raise ValidationError("Run Analyse first to extract products from this BOQ.")
        if boq.status in {BOQStatus.PROCESSING, BOQStatus.MATCHING}:
            raise ValidationError("Wait for the current job to finish.")

        previous_status = boq.status
        self._set_status(boq, BOQStatus.PROCESSING)
        try:
            boq_payload, _make_list_payload = load_extract_data(boq)
            boq_data = structure_for_analysis(boq_payload)
            extraction = BOQExtractionService(boq_data).extract_anchor(row_id)
            anchor_id = str(extraction.get("anchor_row_id") or row_id)

            replacements: list[dict[str, Any]] = []
            for row in extraction.get("rows") or []:
                existing_row = next(
                    (
                        item
                        for item in (existing.get("rows") or [])
                        if str(item.get("row_id")) == str(row.get("row_id"))
                    ),
                    {},
                )
                make_list = existing_row.get("make_list") if str(row.get("row_id")) == anchor_id else None
                replacement = {
                    **row,
                    "product_matches": [],
                }
                if make_list:
                    replacement["make_list"] = make_list
                replacements.append(replacement)

            replacements = self._enrich_extracted_attributes(
                replacements,
                database_version_id=int(existing.get("database_version_id") or 0) or None,
            )
            replacements = rehydrate_analysis_rows_quantity(boq_data, replacements)
            updated_rows = _replace_rows(list(existing.get("rows") or []), replacements)
            analysis_payload = {
                **existing,
                "schema_version": 2,
                "phase": PHASE_EXTRACTED,
                "boq_id": boq.pk,
                "boq_name": boq.boq_name,
                "stats": _compute_extraction_stats(updated_rows),
                "extraction": {
                    **(existing.get("extraction") or {}),
                    "schema_version": extraction.get("schema_version"),
                    "last_row_reextract": anchor_id,
                },
                "rows": updated_rows,
            }
            persist_status = self._status_after_row_work(previous_status)
            self._persist_analysis(boq, analysis_payload, persist_status)
            logger.info("BOQ row re-extraction completed for id=%s row=%s", boq.pk, anchor_id)
            return analysis_payload
        except Exception as exc:
            logger.exception("BOQ row re-extraction failed for id=%s row=%s", boq.pk, row_id)
            self._set_status(boq, previous_status if previous_status else BOQStatus.ANALYSIS_FAILED)
            if isinstance(exc, (AIServiceError, BOQAIError, ValidationError)):
                raise
            raise BOQAIError(f"BOQ row re-extraction failed: {exc}") from exc

    @staticmethod
    def _enrich_extracted_attributes(
        rows: list[dict[str, Any]],
        database_version_id: int | None = None,
        progress_callback=None,
    ) -> list[dict[str, Any]]:
        """Map BOQ-extracted products to top Rate_Master neighbors.

        First pass maps every product. A second pass rematches only weak
        (&lt;50%) products with refine=True so initial Analyse gains the same
        BOQ-section + wider-recall path as expert Re-analyse.
        """
        version_id = int(database_version_id or 0)
        if not version_id:
            active_version = get_active_database_version()
            version_id = int(active_version.pk) if active_version else 0
        if not version_id:
            logger.warning("Attribute enrichment skipped: no active master database")
            return rows
        try:
            mapper = ProductAIMappingService(version_id)
            product_count = sum(len(row.get("products") or []) for row in rows)
            product_count = max(int(product_count or 0), 1)

            def _on_first(done: int, total: int) -> None:
                if not progress_callback:
                    return
                # First pass occupies [0, product_count] of overall
                # [0, product_count + refine_total]. Use 2x until refine starts.
                first_total = max(int(total or 0), product_count, 1)
                progress_callback(min(int(done or 0), first_total), first_total * 2)

            mapped = mapper.map_rows(
                rows,
                progress_callback=_on_first,
                blank_weak_inputs=False,
            )

            def _on_refine(done: int, total: int) -> None:
                if not progress_callback:
                    return
                refine_total = max(int(total or 0), 1)
                overall_total = product_count + refine_total
                progress_callback(
                    min(product_count + int(done or 0), overall_total),
                    overall_total,
                )

            refined = mapper.refine_rows(
                mapped,
                passes=1,
                min_confidence=ANALYSIS_INPUT_FILL_CONFIDENCE,
                progress_callback=_on_refine,
            )
            # Blank weak inputs only after refine so rematch still has identity fields.
            return mapper.apply_weak_match_blanking(refined)
        except Exception:
            logger.exception("AI product mapping failed; keeping AI-extracted attributes")
            return rows

    def ensure_attribute_enrichment(self) -> bool:
        """
        Backfill DB product/attribute mapping for extracted products missing schema.

        Uses AI mapping when available (SQL/Chroma candidate recall + attribute map).
        """
        boq = self._get_boq()
        analysis = dict(boq.analysis_data or {})
        rows = list(analysis.get("rows") or [])
        if not rows:
            return False
        if not any(
            product_needs_attribute_enrichment(product)
            for row in rows
            for product in (row.get("products") or [])
        ):
            return False

        active_version = get_active_database_version()
        if active_version is None:
            logger.warning("Attribute enrichment backfill skipped: no active master database")
            return False

        try:
            mapper = ProductAIMappingService(active_version.pk)
            updated_rows = mapper.map_rows(rows, only_missing=True)
        except Exception:
            logger.exception("AI product mapping backfill failed for BOQ id=%s", boq.pk)
            return False

        analysis["rows"] = updated_rows
        safe_analysis = json_safe(analysis)
        save_boq_analysis_json(boq.boq_name, safe_analysis)
        safe_analysis["analysis_json_path"] = analysis_json_relative_path(boq.boq_name)
        boq.analysis_data = safe_analysis
        boq.save(update_fields=["analysis_data"])
        logger.info("Backfilled AI product mappings for BOQ id=%s (%s)", boq.pk, boq.boq_name)
        return True

    def _get_boq(self) -> BOQ:
        try:
            return BOQ.objects.get(pk=self.boq_id)
        except BOQ.DoesNotExist:
            logger.error(
                "BOQ pipeline skipped: id=%s does not exist (deleted BOQ or stale Celery task)",
                self.boq_id,
            )
            raise BOQAIError(f"BOQ id={self.boq_id} not found.") from None

    def _persist_analysis(self, boq: BOQ, analysis_payload: dict[str, Any], status: str) -> None:
        # Strip Decimal/datetime so psycopg3 JSON dumps never fail.
        safe_payload = json_safe(analysis_payload)
        save_boq_analysis_json(boq.boq_name, safe_payload)
        safe_payload["analysis_json_path"] = analysis_json_relative_path(boq.boq_name)
        # Use queryset update so a BOQ deleted mid-Celery job does not raise
        # ``Save with update_fields did not affect any rows``.
        updated = BOQ.objects.filter(pk=boq.pk).update(
            analysis_data=safe_payload,
            status=status,
        )
        if not updated:
            logger.error(
                "BOQ persist skipped: id=%s was deleted while analysis ran",
                boq.pk,
            )
            raise BOQAIError(
                f"BOQ id={boq.pk} was deleted while analysis was running."
            )
        boq.analysis_data = safe_payload
        boq.status = status

    @staticmethod
    def _set_status(boq: BOQ, status: str) -> None:
        updated = BOQ.objects.filter(pk=boq.pk).update(status=status)
        if not updated:
            logger.error(
                "BOQ status update skipped: id=%s missing (deleted during job)",
                boq.pk,
            )
            raise BOQAIError(
                f"BOQ id={boq.pk} was deleted while analysis was running."
            )
        boq.status = status

    @staticmethod
    def _notify_user(boq: BOQ, title: str, message: str = "") -> None:
        from apps.notifications.services import notify

        notify(getattr(boq, "user", None), title, message)

    @staticmethod
    def _audit(boq: BOQ, action: str) -> None:
        from apps.audit.services import record

        record(getattr(boq, "user", None), action, "BOQ", boq.boq_name)
