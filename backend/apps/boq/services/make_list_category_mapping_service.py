"""Map make-list material descriptions onto Rate_Master categories and sub-categories."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ai.context import (
    load_rate_master_taxonomy,
    resolve_category_label,
    resolve_sub_category_label,
)
from ai.service import AIService

logger = logging.getLogger("boq_ai")

_BATCH_SIZE = 20

# Common free-text synonyms → canonical category tokens (matched against DB categories).
_DESCRIPTION_HINTS: tuple[tuple[str, str], ...] = (
    ("extinguisher", "EXTINGUISHER"),
    ("sprinkler", "SPRINKLER"),
    ("hydrant", "HYDRANT"),
    ("landing valve", "HYDRANT"),
    ("hose reel", "HYDRANT"),
    ("hose", "HYDRANT"),
    ("butterfly valve", "VALVE"),
    ("ball valve", "VALVE"),
    ("sluice", "VALVE"),
    ("non-return", "VALVE"),
    ("non return", "VALVE"),
    ("nrv", "VALVE"),
    ("valve", "VALVE"),
    ("pump", "PUMP"),
    ("pipe", "PIPE"),
    ("fitting", "PIPE"),
    ("coupling", "PIPE"),
    ("tank", "TANK"),
    ("panel", "ACCESSORIES"),
    ("cable tray", "ACCESSORIES"),
    ("switch", "ACCESSORIES"),
    ("meter", "ACCESSORIES"),
)

# Phrase hints that often map onto a sub-category once category is known.
# Phrases are matched against normalized description text (punctuation stripped).
_SUB_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    ("ball valve", "ball"),
    ("butterfly", "butterfly"),
    ("sluice", "sluice"),
    ("non return", "non return"),
    ("jockey", "jockey"),
    ("diesel", "diesel"),
    ("hydrant pump", "hydrant"),
    ("sprinkler pump", "sprinkler"),
    ("hose reel", "hose reel"),
    ("hose box", "hose box"),
    ("fire hose", "fire hose"),
    ("branch pipe", "branch"),
    ("air cushion", "air cushion"),
    ("pressure vessel", "pressure vessel"),
    ("mild steel", "ms"),
    ("m s", "ms"),
    ("galvan", "gi"),
    ("g i", "gi"),
    ("abc", "abc"),
    ("co2", "co2"),
    ("foam", "foam"),
    ("dcp", "dcp"),
)


def _normalize(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _token_set(text: str) -> set[str]:
    return {token for token in _normalize(text).split() if len(token) > 1}


def _heuristic_sub_category(
    description: str,
    *,
    category: str | None,
    sub_categories_by_category: dict[str, list[str]],
) -> str | None:
    if not description or not category:
        return None
    text = _normalize(description)
    for phrase, hint in _SUB_CATEGORY_HINTS:
        if phrase in text:
            resolved = resolve_sub_category_label(
                hint,
                category=category,
                sub_categories_by_category=sub_categories_by_category,
            )
            if resolved:
                return resolved

    desc_tokens = _token_set(description)
    best = None
    best_score = 0.0
    for sub in sub_categories_by_category.get(category) or []:
        sub_tokens = _token_set(sub)
        if not sub_tokens:
            continue
        overlap = desc_tokens & sub_tokens
        if not overlap:
            continue
        score = 100.0 * len(overlap) / max(len(sub_tokens), 1)
        if score > best_score:
            best_score = score
            best = sub
    if best_score >= 50:
        return best
    return None


def _heuristic_category(
    description: str,
    categories: list[str],
    sub_categories_by_category: dict[str, list[str]],
) -> tuple[str | None, str | None, float]:
    """Fast synonym / token match before calling AI."""
    if not description or not categories:
        return None, None, 0.0
    text = _normalize(description)
    for phrase, hint in _DESCRIPTION_HINTS:
        if phrase in text:
            resolved = resolve_category_label(hint, categories)
            if resolved:
                sub = _heuristic_sub_category(
                    description,
                    category=resolved,
                    sub_categories_by_category=sub_categories_by_category,
                )
                return resolved, sub, 70.0

    desc_tokens = _token_set(description)
    best_cat = None
    best_score = 0.0
    for category in categories:
        cat_tokens = _token_set(category)
        if not cat_tokens:
            continue
        overlap = desc_tokens & cat_tokens
        if not overlap:
            continue
        score = 100.0 * len(overlap) / max(len(cat_tokens), 1)
        if score > best_score:
            best_score = score
            best_cat = category
    if best_score >= 50:
        sub = _heuristic_sub_category(
            description,
            category=best_cat,
            sub_categories_by_category=sub_categories_by_category,
        )
        return best_cat, sub, round(best_score, 2)
    return None, None, 0.0


def _materials_from_payload(payload: dict) -> list[dict[str, Any]]:
    """Collect unique make-list materials with approved makes."""
    roles = payload.get("column_roles") or {}
    material_keys = list(roles.get("material_keys") or [])
    make_keys = list(roles.get("make_keys") or [])
    materials: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _material_text(row: dict) -> str:
        display = row.get("display_values") or row.get("values") or row.get("fields") or {}
        for key in (*material_keys, "description", "material", "particulars", "desc"):
            value = display.get(key) if isinstance(display, dict) else None
            if value not in (None, ""):
                return str(value).strip()
        if row.get("approved_makes_list") and isinstance(display, dict):
            for key, value in display.items():
                if key in make_keys:
                    continue
                if value not in (None, "") and len(str(value).strip()) > 2:
                    return str(value).strip()
        return ""

    for row in payload.get("rows") or []:
        material = _material_text(row)
        makes = list(row.get("approved_makes_list") or [])
        if not material or not makes:
            continue
        key = _normalize(material)
        if key in seen:
            continue
        seen.add(key)
        materials.append(
            {
                "material": material,
                "approved_makes_list": makes,
                "row_id": row.get("row_id"),
            }
        )
    return materials


class MakeListCategoryMappingService:
    """
    Map make-list descriptions onto Rate_Master categories and sub-categories so
    approved makes can be selected category-wise (not only by raw description overlap).
    """

    def __init__(self, database_version_id: int | None = None):
        self.database_version_id = database_version_id
        self._ai = AIService()
        self._taxonomy = load_rate_master_taxonomy(database_version_id)

    @staticmethod
    def _mapping_attempted(item: dict) -> bool:
        """
        True when this material has already been through a real mapping pass.

        A material that was mapped and genuinely matched no category is stored as
        ``unmapped``; that is a final answer. Only ``pending`` stubs — written when
        the Rate_Master_Output taxonomy was empty — are worth retrying. Without
        this distinction every unmatched material would re-trigger the AI pass on
        each page load.
        """
        if str(item.get("mapped_category") or "").strip():
            return True
        return str(item.get("source") or "").strip().lower() in {"ai", "unmapped"}

    @classmethod
    def _mappings_incomplete(cls, mappings: list | None) -> bool:
        """True when mappings are missing or some material was never mapped."""
        if not mappings:
            return True
        return any(not cls._mapping_attempted(item) for item in mappings)

    def _can_improve_mappings(self) -> bool:
        """Remapping only helps when Rate_Master_Output taxonomy is available."""
        return bool(self._taxonomy.get("categories"))

    def map_payload(self, payload: dict | None, *, force: bool = False) -> dict:
        """Return make-list payload with ``category_mappings`` and per-row category fields."""
        if not payload or not (payload.get("rows") or []):
            return payload or {}

        existing = payload.get("category_mappings")
        if (
            not force
            and existing
            and not self._mappings_incomplete(existing)
        ):
            return self._apply_mappings_to_rows(dict(payload), existing)

        categories = list(self._taxonomy.get("categories") or [])
        materials = _materials_from_payload(payload)
        if not materials:
            enriched = dict(payload)
            enriched["category_mappings"] = []
            return enriched

        if not categories:
            # Keep prior stubs (if any) but do not invent categories without taxonomy.
            logger.warning(
                "Make-list category mapping skipped: Rate_Master_Output taxonomy is empty"
            )
            if existing is not None:
                return self._apply_mappings_to_rows(dict(payload), existing)
            enriched = dict(payload)
            enriched["category_mappings"] = [
                {
                    "material": item["material"],
                    "material_ref": f"m{index}",
                    "approved_makes_list": list(item.get("approved_makes_list") or []),
                    "mapped_category": None,
                    "mapped_sub_category": None,
                    "confidence": 0.0,
                    "source": "pending",
                    "notes": "Rate_Master_Output taxonomy empty",
                }
                for index, item in enumerate(materials)
            ]
            return self._apply_mappings_to_rows(enriched, enriched["category_mappings"])

        mappings = self._map_materials(materials, categories)
        enriched = dict(payload)
        enriched["category_mappings"] = mappings
        return self._apply_mappings_to_rows(enriched, mappings)

    def ensure_mappings(self, payload: dict | None) -> dict:
        """
        Ensure make-list rows have category mappings.

        Remaps when mappings are missing or incomplete (pending / null category)
        and Rate_Master_Output taxonomy is available. Incomplete stubs left from an
        empty database no longer permanently block remapping.
        """
        if not payload:
            return {}
        existing = payload.get("category_mappings")
        if existing is not None and not self._mappings_incomplete(existing):
            return self._apply_mappings_to_rows(dict(payload), existing)
        if existing is not None and self._mappings_incomplete(existing):
            if self._can_improve_mappings():
                return self.map_payload(payload, force=True)
            return self._apply_mappings_to_rows(dict(payload), existing)
        return self.map_payload(payload)

    def _map_materials(
        self,
        materials: list[dict[str, Any]],
        categories: list[str],
    ) -> list[dict[str, Any]]:
        by_category = dict(self._taxonomy.get("sub_categories_by_category") or {})
        mapped: list[dict[str, Any]] = []
        needs_ai: list[tuple[int, dict[str, Any]]] = []

        for index, item in enumerate(materials):
            category, sub_category, confidence = _heuristic_category(
                item["material"],
                categories,
                by_category,
            )
            entry = {
                "material": item["material"],
                "material_ref": f"m{index}",
                "approved_makes_list": list(item.get("approved_makes_list") or []),
                "mapped_category": category,
                "mapped_sub_category": sub_category,
                "confidence": confidence,
                "source": "heuristic" if category else "pending",
                "notes": "",
            }
            mapped.append(entry)
            if category is None or confidence < 65 or sub_category is None:
                needs_ai.append((index, item))

        if needs_ai and categories and self._ai.is_enabled():
            try:
                ai_by_ref = self._run_ai_batches(needs_ai, categories)
            except Exception:
                logger.exception("AI make-list category mapping failed; keeping heuristics")
                ai_by_ref = {}
            for index, item in needs_ai:
                ref = f"m{index}"
                ai_result = ai_by_ref.get(ref) or {}
                category = ai_result.get("category")
                if category:
                    resolved = resolve_category_label(str(category), categories)
                    if resolved is None and str(category).strip() in categories:
                        resolved = str(category).strip()
                    if resolved:
                        mapped[index]["mapped_category"] = resolved
                        raw_sub = str(ai_result.get("sub_category") or "").strip()
                        resolved_sub = resolve_sub_category_label(
                            raw_sub,
                            category=resolved,
                            sub_categories_by_category=by_category,
                        )
                        if not resolved_sub:
                            resolved_sub = _heuristic_sub_category(
                                item["material"],
                                category=resolved,
                                sub_categories_by_category=by_category,
                            )
                        mapped[index]["mapped_sub_category"] = resolved_sub
                        try:
                            mapped[index]["confidence"] = float(ai_result.get("confidence") or 75)
                        except (TypeError, ValueError):
                            mapped[index]["confidence"] = 75.0
                        mapped[index]["source"] = "ai"
                        mapped[index]["notes"] = str(ai_result.get("notes") or "")
                        continue
                if mapped[index]["mapped_category"] is None:
                    mapped[index]["source"] = "unmapped"
                    mapped[index]["notes"] = str(ai_result.get("notes") or "No category match.")
                elif mapped[index]["mapped_sub_category"] is None:
                    # Keep heuristic category; try one more sub-category pass.
                    mapped[index]["mapped_sub_category"] = _heuristic_sub_category(
                        item["material"],
                        category=mapped[index]["mapped_category"],
                        sub_categories_by_category=by_category,
                    )

        return mapped

    def _run_ai_batches(
        self,
        needs_ai: list[tuple[int, dict[str, Any]]],
        categories: list[str],
    ) -> dict[str, dict[str, Any]]:
        template = AIService.load_prompt("map_make_list_categories.txt")
        taxonomy_payload = {
            "categories": categories,
            "sub_categories_by_category": self._taxonomy.get("sub_categories_by_category") or {},
        }
        by_ref: dict[str, dict[str, Any]] = {}
        for start in range(0, len(needs_ai), _BATCH_SIZE):
            batch = needs_ai[start : start + _BATCH_SIZE]
            materials_payload = [
                {
                    "material_ref": f"m{index}",
                    "description": item["material"],
                    "approved_makes": item.get("approved_makes_list") or [],
                }
                for index, item in batch
            ]
            prompt = (
                template.replace("{{TAXONOMY}}", json.dumps(taxonomy_payload, ensure_ascii=False))
                .replace(
                    "{{MATERIALS_PAYLOAD}}",
                    json.dumps(materials_payload, ensure_ascii=False),
                )
            )
            response = self._ai.complete_json(
                prompt,
                template_name="map_make_list_categories.txt",
            )
            for entry in response.get("mappings") or []:
                ref = str(entry.get("material_ref") or "")
                if ref:
                    by_ref[ref] = entry
        return by_ref

    @staticmethod
    def _apply_mappings_to_rows(payload: dict, mappings: list[dict[str, Any]]) -> dict:
        """Stamp mapped_category / mapped_sub_category onto make-list rows."""
        by_material = {
            _normalize(str(item.get("material") or "")): item
            for item in mappings
            if item.get("material")
        }
        roles = payload.get("column_roles") or {}
        material_keys = list(roles.get("material_keys") or [])
        updated_rows: list[dict] = []
        for row in payload.get("rows") or []:
            display = row.get("display_values") or row.get("values") or {}
            material = ""
            for key in (*material_keys, "description", "material", "particulars", "desc"):
                if isinstance(display, dict) and display.get(key) not in (None, ""):
                    material = str(display.get(key)).strip()
                    break
            mapping = by_material.get(_normalize(material)) if material else None
            if not mapping:
                updated_rows.append(row)
                continue
            updated_rows.append(
                {
                    **row,
                    "mapped_category": mapping.get("mapped_category"),
                    "mapped_sub_category": mapping.get("mapped_sub_category"),
                    "category_mapping_confidence": mapping.get("confidence"),
                    "category_mapping_source": mapping.get("source"),
                }
            )
        payload["rows"] = updated_rows
        payload["category_mappings"] = mappings
        return payload
