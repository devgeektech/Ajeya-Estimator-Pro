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
    expand_make_list_search_text,
    format_synonym_map_for_ai,
)

logger = logging.getLogger("boq_ai")

_BATCH_SIZE = 20

# Bump when mapping rules change so ensure_mappings remaps stored make lists.
_MAPPING_VERSION = 11

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
        "types",
        "all",
        "any",
        "with",
        "for",
        "and",
        "the",
        "etc",
        "fire",
        "fighting",
        "system",
        "systems",
        "equipment",
        "covered",
        "elsewhere",
        "else",
        "where",
        "not",
        "miscellaneous",
        "misc",
        "general",
    }
)

_ALL_TYPES_MARKERS = (
    "all types",
    "all type",
    "any type",
    "any types",
    "all kinds",
    "all kind",
    "of all type",
    "of all types",
)


def _normalize(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_all_types_line(description: str) -> bool:
    """True when the make-list line is generic (All Types) — leave sub blank."""
    text = _normalize(description)
    if not text:
        return False
    if any(marker in text for marker in _ALL_TYPES_MARKERS):
        return True
    # Catch-all equipment lines with no specific product noun.
    if "not covered" in text and "equipment" in text:
        return True
    return False


def _normalize_targets(
    raw_targets: Any,
    *,
    categories: list[str],
    by_category: dict[str, list[str]],
) -> list[dict[str, str | None]]:
    """Validate AI/heuristic target list against taxonomy (deduped)."""
    if not isinstance(raw_targets, list):
        return []
    cleaned: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_targets:
        if not isinstance(item, dict):
            continue
        raw_cat = str(item.get("category") or "").strip()
        if not raw_cat:
            continue
        category = resolve_category_label(raw_cat, categories) or (
            raw_cat if raw_cat in categories else None
        )
        if not category:
            continue
        raw_sub = str(item.get("sub_category") or "").strip()
        sub = None
        if raw_sub:
            sub = resolve_sub_category_label(
                raw_sub,
                category=category,
                sub_categories_by_category=by_category,
            )
        key = (_normalize(category), _normalize(sub or ""))
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"category": category, "sub_category": sub})
    return cleaned


def _targets_from_single(
    category: str | None,
    sub_category: str | None,
) -> list[dict[str, str | None]]:
    if not category:
        return []
    return [{"category": category, "sub_category": sub_category or None}]


def _primary_from_targets(
    targets: list[dict[str, str | None]],
) -> tuple[str | None, str | None]:
    if not targets:
        return None, None
    first = targets[0]
    return first.get("category"), first.get("sub_category")


def format_mapped_targets_display(
    targets: list[dict[str, str | None]] | None,
    *,
    category: str | None = None,
    sub_category: str | None = None,
) -> tuple[str, str]:
    """UI strings for Category / Subcategory columns (supports multi-target)."""
    rows = list(targets or [])
    if not rows and category:
        rows = _targets_from_single(category, sub_category)
    if not rows:
        return "", ""

    cat_parts: list[str] = []
    sub_parts: list[str] = []
    for item in rows:
        cat = str(item.get("category") or "").strip()
        sub = str(item.get("sub_category") or "").strip()
        if cat and cat not in cat_parts:
            cat_parts.append(cat)
        if sub:
            label = f"{cat}: {sub}" if cat and len(rows) > 1 else sub
            if label not in sub_parts:
                sub_parts.append(label)
        elif cat and len(rows) > 1:
            label = f"{cat}: (all)"
            if label not in sub_parts:
                sub_parts.append(label)
    return " | ".join(cat_parts), " | ".join(sub_parts)


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
    # "All Types" / catch-all equipment lines — do not invent Pendant vs Upright etc.
    if _is_all_types_line(description):
        text = expand_make_list_search_text(description) or _normalize(description)
        # Pure rosette-plate lines may still map the product sub (not a head type).
        if _normalize(category) == "accessories" and "rosette" in text and "sprinkler" not in text:
            return resolve_sub_category_label(
                "rosette",
                category=category,
                sub_categories_by_category=sub_categories_by_category,
            )
        return None
    text = expand_make_list_search_text(description) or _normalize(description)

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

    desc_tokens = _token_set(text)
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
    text = expand_make_list_search_text(description) or _normalize(description)
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

    desc_tokens = _token_set(text)
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


def _heuristic_targets(
    description: str,
    *,
    primary_category: str | None,
    primary_sub: str | None,
    categories: list[str],
    sub_categories_by_category: dict[str, list[str]],
) -> list[dict[str, str | None]]:
    """Expand primary heuristic into multi-target when text names more families."""
    targets = _targets_from_single(primary_category, primary_sub)
    if not description:
        return targets
    text = expand_make_list_search_text(description) or _normalize(description)
    primary_norm = _normalize(primary_category or "")

    # Compound sprinkler + rosette: keep sprinkler family + accessories/rosette.
    if "sprinkler" in text and "rosette" in text:
        sprinkler = resolve_category_label("SPRINKLER", categories)
        accessories = resolve_category_label("ACCESSORIES", categories)
        if sprinkler and not any(_normalize(str(t.get("category") or "")) == _normalize(sprinkler) for t in targets):
            targets.insert(0, {"category": sprinkler, "sub_category": None})
        if accessories:
            rosette_sub = resolve_sub_category_label(
                "rosette",
                category=accessories,
                sub_categories_by_category=sub_categories_by_category,
            )
            if not any(
                _normalize(str(t.get("category") or "")) == _normalize(accessories)
                and _normalize(str(t.get("sub_category") or ""))
                == _normalize(rosette_sub or "")
                for t in targets
            ):
                targets.append({"category": accessories, "sub_category": rosette_sub})

    # Catch-all fire equipment with no specific product → umbrella hydrant.
    if (
        not targets
        and "equipment" in text
        and "not covered" in text
        and ("fire" in text or "fighting" in text)
    ):
        hydrant = resolve_category_label("HYDRANT", categories)
        if hydrant:
            targets = [{"category": hydrant, "sub_category": None}]

    # Dedupe while preserving order.
    cleaned: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for item in targets:
        cat = str(item.get("category") or "").strip()
        if not cat:
            continue
        key = (_normalize(cat), _normalize(str(item.get("sub_category") or "")))
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"category": cat, "sub_category": item.get("sub_category")})
    # Prefer sprinkler before accessories when both present.
    if primary_norm == "accessories" and any(
        _normalize(str(t.get("category") or "")) == "sprinkler" for t in cleaned
    ):
        cleaned.sort(
            key=lambda t: 0 if _normalize(str(t.get("category") or "")) == "sprinkler" else 1
        )
    return cleaned


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
        """AI-first mapping with multi-target support; heuristic is a soft hint only."""
        by_category = dict(self._taxonomy.get("sub_categories_by_category") or {})
        mapped: list[dict[str, Any]] = []

        for index, item in enumerate(materials):
            category, sub_category, confidence, phrase_matched = _heuristic_category(
                item["material"],
                categories,
                by_category,
            )
            targets = _heuristic_targets(
                item["material"],
                primary_category=category,
                primary_sub=sub_category,
                categories=categories,
                sub_categories_by_category=by_category,
            )
            primary_cat, primary_sub = _primary_from_targets(targets)
            mapped.append(
                {
                    "material": item["material"],
                    "material_ref": f"m{index}",
                    "approved_makes_list": list(item.get("approved_makes_list") or []),
                    "mapped_category": primary_cat,
                    "mapped_sub_category": primary_sub,
                    "mapped_targets": targets,
                    "confidence": confidence,
                    "source": "heuristic" if primary_cat else "pending",
                    "notes": "",
                    "phrase_matched": phrase_matched,
                }
            )

        # AI understands free-text / compound / catch-all lines dynamically.
        if categories and self._ai.is_enabled() and mapped:
            needs_ai = list(enumerate(materials))
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
            targets = list(entry.get("mapped_targets") or [])
            if not targets and entry.get("mapped_category"):
                targets = _targets_from_single(
                    entry.get("mapped_category"),
                    entry.get("mapped_sub_category"),
                )
                entry["mapped_targets"] = targets
            primary_cat, primary_sub = _primary_from_targets(targets)
            if primary_cat:
                entry["mapped_category"] = primary_cat
                entry["mapped_sub_category"] = primary_sub
            if entry.get("mapped_category") is None and entry.get("source") == "pending":
                entry["source"] = "unmapped"
                entry["notes"] = entry.get("notes") or "No category match."
                entry["mapped_targets"] = []
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
        """Prefer validated AI targets; keep heuristic only when AI returns nothing."""
        try:
            ai_conf = float(ai_result.get("confidence") or 0)
        except (TypeError, ValueError):
            ai_conf = 0.0

        raw_targets = ai_result.get("targets")
        targets = _normalize_targets(
            raw_targets,
            categories=categories,
            by_category=by_category,
        )
        # Legacy single-target AI shape.
        if not targets:
            raw_cat = str(ai_result.get("category") or "").strip()
            resolved = resolve_category_label(raw_cat, categories) if raw_cat else None
            if resolved is None and raw_cat in categories:
                resolved = raw_cat
            raw_sub = str(ai_result.get("sub_category") or "").strip()
            resolved_sub = None
            if resolved and raw_sub:
                resolved_sub = resolve_sub_category_label(
                    raw_sub,
                    category=resolved,
                    sub_categories_by_category=by_category,
                )
            targets = _targets_from_single(resolved, resolved_sub)

        if targets:
            primary_cat, primary_sub = _primary_from_targets(targets)
            entry["mapped_targets"] = targets
            entry["mapped_category"] = primary_cat
            entry["mapped_sub_category"] = primary_sub
            entry["source"] = "ai"
            entry["confidence"] = ai_conf or 80.0
            entry["notes"] = str(ai_result.get("notes") or "")
            return

        # AI empty — keep heuristic targets if present.
        if entry.get("mapped_category"):
            if not entry.get("mapped_targets"):
                entry["mapped_targets"] = _targets_from_single(
                    entry.get("mapped_category"),
                    entry.get("mapped_sub_category"),
                )
            return

        entry["source"] = "unmapped"
        entry["notes"] = str(ai_result.get("notes") or "No category match.")
        entry["mapped_targets"] = []
        entry["mapped_category"] = None
        entry["mapped_sub_category"] = None

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
                        "heuristic_targets": prior.get("mapped_targets") or [],
                    }
                )
            prompt = (
                template.replace("{{SYNONYM_MAP}}", format_synonym_map_for_ai())
                .replace("{{TAXONOMY}}", json.dumps(taxonomy_payload, ensure_ascii=False))
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
        """Stamp mapped category/sub/targets onto make-list rows."""
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
            targets = list(mapping.get("mapped_targets") or [])
            if not targets and mapping.get("mapped_category"):
                targets = _targets_from_single(
                    mapping.get("mapped_category"),
                    mapping.get("mapped_sub_category"),
                )
            cat_display, sub_display = format_mapped_targets_display(
                targets,
                category=mapping.get("mapped_category"),
                sub_category=mapping.get("mapped_sub_category"),
            )
            updated_rows.append(
                {
                    **row,
                    "mapped_category": mapping.get("mapped_category"),
                    "mapped_sub_category": mapping.get("mapped_sub_category"),
                    "mapped_targets": targets,
                    "mapped_category_display": cat_display or mapping.get("mapped_category"),
                    "mapped_sub_category_display": sub_display
                    or mapping.get("mapped_sub_category"),
                    "category_mapping_confidence": mapping.get("confidence"),
                    "category_mapping_source": mapping.get("source"),
                }
            )
        payload["rows"] = updated_rows
        payload["category_mappings"] = mappings
        payload["category_mapping_version"] = _MAPPING_VERSION
        return payload
