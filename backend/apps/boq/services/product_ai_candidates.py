"""Candidate recall / seed helpers for Product AI mapping."""
from __future__ import annotations

from typing import Any

from apps.boq.services.boq_row_fields import is_filled as _is_filled
from apps.boq.services.product_ai_common import (
    _AI_CANDIDATE_LIMIT,
    _CANDIDATE_LIMIT,
    _RECALL_CHROMA_LIMIT,
    _candidate_snapshot,
)
from apps.boq.services.product_matching_service import (
    ProductMatchingService,
    structured_match_score,
)
from apps.database_manager.models import Rate_Master_Output
from utils.product_synonyms import display_material_label

_RECALL_CORE_KEYS = (
    "description_hint",
    "category",
    "sub_category",
    "class",
    "size",
    "unit",
    "capacity",
)


def _recall_identity_blank(product: dict[str, Any]) -> bool:
    """True when Analysis inputs have no usable product identity for recall."""
    for key in _RECALL_CORE_KEYS:
        if _is_filled(product.get(key)):
            return False
    attributes = product.get("attributes") or {}
    if isinstance(attributes, dict):
        for value in attributes.values():
            if _is_filled(value):
                return False
    return True


class ProductAICandidatesMixin:
    """Chroma / SQL candidate recall and prior-Product_ID seeding."""

    # Provided by ProductAIMappingService.__init__.
    database_version_id: int
    _matcher: ProductMatchingService

    def _product_for_recall(
        self,
        product: dict[str, Any],
        *,
        refine: bool = False,
    ) -> dict[str, Any]:
        """Build Chroma/SQL query input from UI product fields (+ slot line).

        Normally full section text stays on ``_boq_row`` for the AI picker only —
        dumping titles (e.g. ``Yard Hydrant System``) into recall drowned the
        purchasable slot (pipe / valve).

        Exception — empty-input Re-analyse: when core fields are blank, fold the
        full section into ``description_hint`` so Chroma/SQL can surface nearest
        neighbors (initial Analyse often left these blank after weak blanking).

        On Re-analyse (``refine=True``), an expert-edited ``description_hint``
        leads recall so stale Category/Sub from a prior weak match do not win.
        """
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

        raw_boq = product.get("_boq_row")
        boq_row: dict[str, Any] = raw_boq if isinstance(raw_boq, dict) else {}
        section_text = str(boq_row.get("description") or "").strip()
        slot_line = str(boq_row.get("slot_description") or "").strip()
        hint = str(product_for_recall.get("description_hint") or "").strip()

        # Empty Re-analyse: section is the only identity — send it into recall.
        if refine and _recall_identity_blank(product_for_recall) and section_text:
            product_for_recall["description_hint"] = section_text
            product_for_recall["_hint_first_recall"] = True
            product_for_recall["_section_first_recall"] = True
            product_for_recall.pop("category", None)
            product_for_recall.pop("sub_category", None)
            return product_for_recall

        # Expert understanding leads rematch recall; section stays secondary evidence.
        if refine and hint:
            product_for_recall["_hint_first_recall"] = True
            product_for_recall.pop("category", None)
            product_for_recall.pop("sub_category", None)
            if section_text and section_text.lower() not in hint.lower():
                product_for_recall["description_hint"] = (
                    f"{hint}\n{section_text[:400]}".strip()
                )
            return product_for_recall

        if slot_line and slot_line.lower() not in hint.lower():
            # Prefer the qty/unit slot line as supporting evidence — not the full
            # section title dump when identity fields already exist.
            product_for_recall["description_hint"] = (
                f"{hint}\n{slot_line}".strip() if hint else slot_line
            )

        return product_for_recall

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

        if len(merged) >= _AI_CANDIDATE_LIMIT:
            return merged[:_AI_CANDIDATE_LIMIT]

        seed_ids = [rate_id for rate_id, _conf in seeds]
        rate_rows = getattr(Rate_Master_Output, "objects").filter(
            pk__in=seed_ids,
            database_version_id=self.database_version_id,
        )
        rate_map = {rate.pk: rate for rate in rate_rows}
        product_only = dict(product)
        product_only["make_hint"] = None
        for rate_id, _ignored in seeds:
            if len(merged) >= _AI_CANDIDATE_LIMIT:
                break
            rate = rate_map.get(rate_id)
            if rate is None:
                continue
            # Re-score against current UI fields — never reuse stale listed %.
            score, _breakdown = structured_match_score(product_only, rate)
            _append(_candidate_snapshot(rate, confidence=round(float(score), 2)))

        merged.sort(
            key=lambda item: (
                -_confidence_value(item.get("confidence")),
                int(item.get("id") or 0),
            ),
        )
        return merged[:_AI_CANDIDATE_LIMIT]

    def _recall_candidates(
        self,
        product: dict[str, Any],
        *,
        chroma_limit: int = _RECALL_CHROMA_LIMIT,
    ) -> list[dict[str, Any]]:
        # Analysis finds the product without make — Make & Vendor selects make later.
        product_for_recall = self._product_for_recall(product)
        match = self._matcher.match_product(
            product_for_recall,
            chroma_limit=max(int(chroma_limit or _RECALL_CHROMA_LIMIT), _RECALL_CHROMA_LIMIT),
            result_limit=_AI_CANDIDATE_LIMIT,
        )
        return self._snapshots_from_match(match, product_for_recall)

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
            if len(rate_ids) >= _AI_CANDIDATE_LIMIT:
                break

        rate_rows = getattr(Rate_Master_Output, "objects").filter(
            pk__in=rate_ids,
            database_version_id=self.database_version_id,
        )
        rate_map = {rate.pk: rate for rate in rate_rows}
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
                if len(snapshots) >= _AI_CANDIDATE_LIMIT:
                    break

        snapshots.sort(
            key=lambda item: (
                -_confidence_value(item.get("confidence")),
                int(item.get("id") or 0),
            ),
        )
        return snapshots[:_AI_CANDIDATE_LIMIT]
