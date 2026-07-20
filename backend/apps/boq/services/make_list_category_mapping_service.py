"""Map make-list material descriptions onto Rate_Master categories."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ai.service import AIService
from apps.database_manager.models import Rate_Master
from apps.database_manager.services.activation import get_active_database_version

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


def _normalize(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _token_set(text: str) -> set[str]:
    return {token for token in _normalize(text).split() if len(token) > 1}


def list_rate_master_categories(database_version_id: int | None = None) -> list[str]:
    """Distinct Category values from the active (or given) Rate_Master."""
    version = None
    if database_version_id is not None:
        from apps.database_manager.models import DatabaseVersion

        version = DatabaseVersion.objects.filter(pk=database_version_id).first()
    else:
        version = get_active_database_version()
    if version is None:
        return []
    values = (
        Rate_Master.objects.filter(database_version=version)
        .exclude(Category__isnull=True)
        .exclude(Category="")
        .values_list("Category", flat=True)
        .distinct()
    )
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _resolve_category_label(hint: str, categories: list[str]) -> str | None:
    """Match a hint token/phrase onto an actual DB category label."""
    if not hint or not categories:
        return None
    hint_norm = _normalize(hint)
    by_norm = {_normalize(cat): cat for cat in categories}
    if hint_norm in by_norm:
        return by_norm[hint_norm]
    # Hint contained in category or category contained in hint.
    for cat_norm, cat in by_norm.items():
        if hint_norm == cat_norm or hint_norm in cat_norm or cat_norm in hint_norm:
            return cat
    return None


def _heuristic_category(description: str, categories: list[str]) -> tuple[str | None, float]:
    """Fast synonym / token match before calling AI."""
    if not description or not categories:
        return None, 0.0
    text = _normalize(description)
    for phrase, hint in _DESCRIPTION_HINTS:
        if phrase in text:
            resolved = _resolve_category_label(hint, categories)
            if resolved:
                return resolved, 70.0

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
        return best_cat, round(best_score, 2)
    return None, 0.0


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
    Map make-list descriptions onto Rate_Master categories so approved makes
    can be selected category-wise (not only by raw description token overlap).
    """

    def __init__(self, database_version_id: int | None = None):
        self.database_version_id = database_version_id
        self._ai = AIService()

    def map_payload(self, payload: dict | None) -> dict:
        """Return make-list payload with ``category_mappings`` and per-row category fields."""
        if not payload or not (payload.get("rows") or []):
            return payload or {}

        if payload.get("category_mappings"):
            return self._apply_mappings_to_rows(dict(payload), payload["category_mappings"])

        categories = list_rate_master_categories(self.database_version_id)
        materials = _materials_from_payload(payload)
        if not materials:
            enriched = dict(payload)
            enriched["category_mappings"] = []
            return enriched

        mappings = self._map_materials(materials, categories)
        enriched = dict(payload)
        enriched["category_mappings"] = mappings
        return self._apply_mappings_to_rows(enriched, mappings)

    def ensure_mappings(self, payload: dict | None) -> dict:
        """Map when ``category_mappings`` is missing; otherwise return payload as-is."""
        if not payload:
            return {}
        if payload.get("category_mappings") is not None:
            # Still backfill row fields if mappings exist but rows lack category.
            return self._apply_mappings_to_rows(dict(payload), payload.get("category_mappings") or [])
        return self.map_payload(payload)

    def _map_materials(
        self,
        materials: list[dict[str, Any]],
        categories: list[str],
    ) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        needs_ai: list[tuple[int, dict[str, Any]]] = []

        for index, item in enumerate(materials):
            category, confidence = _heuristic_category(item["material"], categories)
            entry = {
                "material": item["material"],
                "material_ref": f"m{index}",
                "approved_makes_list": list(item.get("approved_makes_list") or []),
                "mapped_category": category,
                "mapped_sub_category": None,
                "confidence": confidence,
                "source": "heuristic" if category else "pending",
                "notes": "",
            }
            mapped.append(entry)
            if category is None or confidence < 65:
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
                    resolved = _resolve_category_label(str(category), categories)
                    if resolved is None and str(category).strip() in categories:
                        resolved = str(category).strip()
                    if resolved:
                        mapped[index]["mapped_category"] = resolved
                        mapped[index]["mapped_sub_category"] = (
                            str(ai_result.get("sub_category") or "").strip() or None
                        )
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

        return mapped

    def _run_ai_batches(
        self,
        needs_ai: list[tuple[int, dict[str, Any]]],
        categories: list[str],
    ) -> dict[str, dict[str, Any]]:
        template = AIService.load_prompt("map_make_list_categories.txt")
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
                template.replace("{{CATEGORIES}}", json.dumps(categories, ensure_ascii=False))
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
        """Stamp mapped_category onto make-list rows for UI and constraint lookup."""
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
