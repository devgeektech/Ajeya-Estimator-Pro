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
from utils.product_synonyms import (
    MAKE_LIST_DESCRIPTION_HINTS,
    MAKE_LIST_SUB_CATEGORY_HINTS,
)

logger = logging.getLogger("boq_ai")

_BATCH_SIZE = 20

# Bump when mapping rules change so ensure_mappings remaps stored make lists.
_MAPPING_VERSION = 4

# Tokens too generic to pick a sub-category by overlap alone (e.g. "Alarm Valve"
# must not become BALL VALVE just because both share "valve").
_GENERIC_SUB_TOKENS = frozenset(
    {
        "valve",
        "valves",
        "pipe",
        "pipes",
        "pump",
        "pumps",
        "hose",
        "hoses",
        "tank",
        "tanks",
        "fitting",
        "fittings",
        "type",
        "with",
        "for",
        "and",
        "the",
        "all",
        "etc",
        "fire",
        "fighting",
        "system",
        "systems",
    }
)

def _normalize(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _token_set(text: str) -> set[str]:
    return {token for token in _normalize(text).split() if len(token) > 1}


def _specific_tokens(tokens: set[str]) -> set[str]:
    return {token for token in tokens if token not in _GENERIC_SUB_TOKENS}


def _heuristic_sub_category(
    description: str,
    *,
    category: str | None,
    sub_categories_by_category: dict[str, list[str]],
) -> str | None:
    if not description or not category:
        return None
    text = _normalize(description)

    # Generic "Fire Extinguishers" must not invent ABC / CO2 without a type word.
    if _normalize(category) == "extinguisher":
        type_hits = ("abc", "co2", "foam", "dcp", "fe36", "wet chemical", "water based")
        if not any(token in text for token in type_hits):
            return None

    for phrase, hint in MAKE_LIST_SUB_CATEGORY_HINTS:
        phrase_norm = _normalize(phrase)
        if not phrase_norm or phrase_norm not in text:
            continue
        # Rosette under a sprinkler-primary line stays on sprinkler category.
        if phrase_norm == "rosette" and "sprinkler" in text:
            continue
        # Flexible pipe/connectors only when the line is sprinkler-related.
        if "flexible" in phrase_norm and "sprinkler" not in text:
            continue
        resolved = resolve_sub_category_label(
            hint,
            category=category,
            sub_categories_by_category=sub_categories_by_category,
        )
        if resolved:
            return resolved

    # No foot-valve sub in taxonomy — do not steal Y STRAINER via shared "strainer".
    if "foot valve" in text or text.startswith("foot "):
        return None

    # Bare hose lines under HYDRANT → FIRE HOSE when no reel/box/branch wording.
    if _normalize(category) == "hydrant" and "hose" in text:
        if not any(token in text for token in ("reel", "box", "branch", "landing", "brigade")):
            resolved = resolve_sub_category_label(
                "fire hose",
                category=category,
                sub_categories_by_category=sub_categories_by_category,
            )
            if resolved:
                return resolved

    desc_tokens = _token_set(description)
    specific_desc = _specific_tokens(desc_tokens)
    if not specific_desc:
        return None

    best = None
    best_score = 0.0
    for sub in sub_categories_by_category.get(category) or []:
        # Keep single-letter tokens (e.g. "Y" in Y STRAINER).
        sub_tokens = {
            token for token in _normalize(sub).split() if token and len(token) > 0
        }
        specific_sub = _specific_tokens(sub_tokens) or sub_tokens
        if not specific_sub:
            continue
        overlap = specific_desc & specific_sub
        if not overlap:
            continue
        # Single shared accessory word (strainer) is not enough when the sub also
        # has a distinguishing token the description lacks (e.g. leading "Y").
        distinguishing = specific_sub - overlap
        if distinguishing and len(overlap) == 1 and len(specific_sub) > 1:
            continue
        score = 100.0 * len(overlap) / max(len(specific_sub), 1)
        if score > best_score:
            best_score = score
            best = sub
    # Require a real specific overlap (not shared "valve" alone).
    if best_score >= 60:
        return best
    return None

def _heuristic_category(
    description: str,
    categories: list[str],
    sub_categories_by_category: dict[str, list[str]],
) -> tuple[str | None, str | None, float, bool]:
    """Fast synonym / token match before calling AI.

    Returns ``(category, sub_category, confidence, phrase_matched)``.
    """
    if not description or not categories:
        return None, None, 0.0, False
    text = _normalize(description)
    for phrase, hint in MAKE_LIST_DESCRIPTION_HINTS:
        phrase_norm = _normalize(phrase)
        if not phrase_norm or phrase_norm not in text:
            continue
        # Prefer SPRINKLER when both sprinkler and rosette appear.
        if phrase_norm == "rosette" and "sprinkler" in text:
            continue
        # Flexible connectors / pipe → PIPE only with sprinkler context.
        if "flexible" in phrase_norm and "sprinkler" not in text:
            continue
        resolved = resolve_category_label(hint, categories)
        if resolved:
            sub = _heuristic_sub_category(
                description,
                category=resolved,
                sub_categories_by_category=sub_categories_by_category,
            )
            return resolved, sub, 78.0, True

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
        return best_cat, sub, round(best_score, 2), False
    return None, None, 0.0, False


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
        if row.get("is_section_heading"):
            continue
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

    def _needs_remap(self, payload: dict) -> bool:
        """Remap when rules version changed or stubs are incomplete."""
        if int(payload.get("category_mapping_version") or 0) < _MAPPING_VERSION:
            return True
        return self._mappings_incomplete(payload.get("category_mappings"))

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
            and not self._needs_remap(payload)
        ):
            return self._apply_mappings_to_rows(dict(payload), existing)

        categories = list(self._taxonomy.get("categories") or [])
        materials = _materials_from_payload(payload)
        if not materials:
            enriched = dict(payload)
            enriched["category_mappings"] = []
            enriched["category_mapping_version"] = _MAPPING_VERSION
            return enriched

        if not categories:
            # Keep prior stubs (if any) but do not invent categories without taxonomy.
            logger.warning(
                "Make-list category mapping skipped: Rate_Master_Output taxonomy is empty"
            )
            if existing is not None and not force:
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
            enriched["category_mapping_version"] = _MAPPING_VERSION
            return self._apply_mappings_to_rows(enriched, enriched["category_mappings"])

        mappings = self._map_materials(materials, categories)
        enriched = dict(payload)
        enriched["category_mappings"] = mappings
        enriched["category_mapping_version"] = _MAPPING_VERSION
        return self._apply_mappings_to_rows(enriched, mappings)

    def ensure_mappings(self, payload: dict | None) -> dict:
        """
        Ensure make-list rows have category mappings.

        Remaps when mappings are missing, incomplete (pending stubs), or the
        mapping-rules version is older than the current service version.
        """
        if not payload:
            return {}
        existing = payload.get("category_mappings")
        if existing is not None and not self._needs_remap(payload):
            return self._apply_mappings_to_rows(dict(payload), existing)
        if self._needs_remap(payload):
            if self._can_improve_mappings() or existing is None:
                return self.map_payload(payload, force=True)
            return self._apply_mappings_to_rows(dict(payload), existing or [])
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
            category, sub_category, confidence, phrase_matched = _heuristic_category(
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
                "phrase_matched": phrase_matched,
            }
            mapped.append(entry)
            # Ask AI when category unknown, sub missing, or only weak token overlap.
            if category is None or sub_category is None or (not phrase_matched and confidence < 75):
                needs_ai.append((index, item))

        if needs_ai and categories and self._ai.is_enabled():
            try:
                ai_by_ref = self._run_ai_batches(needs_ai, categories, mapped)
            except Exception:
                logger.exception("AI make-list category mapping failed; keeping heuristics")
                ai_by_ref = {}
            for index, item in needs_ai:
                ref = f"m{index}"
                ai_result = ai_by_ref.get(ref) or {}
                self._merge_ai_result(
                    mapped[index],
                    ai_result,
                    material=item["material"],
                    categories=categories,
                    by_category=by_category,
                )

        for entry in mapped:
            entry.pop("phrase_matched", None)
            if entry.get("mapped_category") is None and entry.get("source") == "pending":
                entry["source"] = "unmapped"
                entry["notes"] = entry.get("notes") or "No category match."
        return mapped

    def _merge_ai_result(
        self,
        entry: dict[str, Any],
        ai_result: dict[str, Any],
        *,
        material: str,
        categories: list[str],
        by_category: dict[str, list[str]],
    ) -> None:
        """Merge AI output without letting a weak AI guess overwrite a solid heuristic."""
        heuristic_cat = entry.get("mapped_category")
        heuristic_sub = entry.get("mapped_sub_category")
        phrase_matched = bool(entry.get("phrase_matched"))
        try:
            heuristic_conf = float(entry.get("confidence") or 0)
        except (TypeError, ValueError):
            heuristic_conf = 0.0

        raw_cat = str(ai_result.get("category") or "").strip()
        resolved = resolve_category_label(raw_cat, categories) if raw_cat else None
        if resolved is None and raw_cat in categories:
            resolved = raw_cat

        try:
            ai_conf = float(ai_result.get("confidence") or 0)
        except (TypeError, ValueError):
            ai_conf = 0.0

        keep_heuristic_category = bool(
            heuristic_cat
            and (
                phrase_matched
                or heuristic_conf >= 70
            )
            and (
                not resolved
                or _normalize(str(resolved)) == _normalize(str(heuristic_cat))
                or ai_conf < max(heuristic_conf, 70) + 5
            )
        )

        chosen_category = heuristic_cat if keep_heuristic_category else resolved
        if not chosen_category and resolved:
            chosen_category = resolved

        if not chosen_category:
            if heuristic_cat is None:
                entry["source"] = "unmapped"
                entry["notes"] = str(ai_result.get("notes") or "No category match.")
            return

        entry["mapped_category"] = chosen_category

        raw_sub = str(ai_result.get("sub_category") or "").strip()
        resolved_sub = resolve_sub_category_label(
            raw_sub,
            category=chosen_category,
            sub_categories_by_category=by_category,
        )
        if not resolved_sub:
            resolved_sub = _heuristic_sub_category(
                material,
                category=chosen_category,
                sub_categories_by_category=by_category,
            )
        # Prefer existing correct heuristic sub when AI could not resolve one.
        if not resolved_sub and heuristic_sub and keep_heuristic_category:
            resolved_sub = heuristic_sub
        # Do not keep a heuristic sub that belongs to a different category after override.
        if resolved_sub:
            entry["mapped_sub_category"] = resolved_sub
        elif not keep_heuristic_category:
            entry["mapped_sub_category"] = None

        if resolved and not keep_heuristic_category:
            entry["source"] = "ai"
            entry["confidence"] = ai_conf or 75.0
            entry["notes"] = str(ai_result.get("notes") or "")
        elif resolved_sub and entry.get("source") == "heuristic" and not heuristic_sub:
            entry["notes"] = str(ai_result.get("notes") or entry.get("notes") or "")
            if ai_conf:
                entry["confidence"] = max(heuristic_conf, min(ai_conf, 90.0))
        elif heuristic_cat is None and resolved:
            entry["source"] = "ai"
            entry["confidence"] = ai_conf or 75.0
            entry["notes"] = str(ai_result.get("notes") or "")

    def _run_ai_batches(
        self,
        needs_ai: list[tuple[int, dict[str, Any]]],
        categories: list[str],
        mapped: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        template = AIService.load_prompt("map_make_list_categories.txt")
        taxonomy_payload = {
            "categories": categories,
            "sub_categories_by_category": self._taxonomy.get("sub_categories_by_category") or {},
        }
        by_ref: dict[str, dict[str, Any]] = {}
        for start in range(0, len(needs_ai), _BATCH_SIZE):
            batch = needs_ai[start : start + _BATCH_SIZE]
            materials_payload = []
            for index, item in batch:
                prior = mapped[index]
                materials_payload.append(
                    {
                        "material_ref": f"m{index}",
                        "description": item["material"],
                        "approved_makes": item.get("approved_makes_list") or [],
                        "heuristic_category": prior.get("mapped_category"),
                        "heuristic_sub_category": prior.get("mapped_sub_category"),
                    }
                )
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
        payload["category_mapping_version"] = payload.get(
            "category_mapping_version", _MAPPING_VERSION
        )
        return payload
