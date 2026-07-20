"""Index make-list approved makes and apply hard filters during matching."""
from __future__ import annotations

import re
from typing import Any, Iterable

LOWEST_MAKE_VALUE = "__lowest__"
LOWEST_MAKE_LABEL = "Lowest price"
LOWEST_MAKE_STORED = "LOWEST PRICE"

_DESCRIPTION_KEYS = (
    "description",
    "item_description",
    "particulars",
    "item",
    "material",
    "materials",
)


def _normalize_make(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().upper())


def _normalize_text(value: str) -> str:
    text = re.sub(r"[^0-9a-zA-Z]+", " ", (value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _token_set(text: str) -> set[str]:
    return {token for token in _normalize_text(text).split() if len(token) > 2}


def _categories_equivalent(left: str, right: str) -> bool:
    a = _normalize_text(left)
    b = _normalize_text(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _description_from_fields(
    fields: dict[str, Any],
    *,
    material_keys: list[str] | None = None,
    make_keys: list[str] | None = None,
) -> str:
    make_key_set = {str(key) for key in (make_keys or [])}
    for key in material_keys or []:
        if key in make_key_set:
            continue
        value = fields.get(key)
        if value not in (None, ""):
            return str(value).strip()
    for key in _DESCRIPTION_KEYS:
        if key in make_key_set:
            continue
        value = fields.get(key)
        if value not in (None, ""):
            return str(value).strip()
    for key, value in fields.items():
        if key in make_key_set:
            continue
        if isinstance(value, str) and len(value.strip()) > 8:
            return value.strip()
    return ""


def walk_rows_tree(nodes: Iterable[dict]) -> list[dict]:
    """Depth-first flatten of ``rows_tree`` nodes."""
    flat: list[dict] = []
    for node in nodes:
        flat.append(node)
        flat.extend(walk_rows_tree(node.get("children") or []))
    return flat


class MakeListConstraintService:
    """Map BOQ products to approved makes via category mapping + description match."""

    def __init__(self, make_list_data: dict | None):
        self._entries: list[dict[str, Any]] = []
        self._by_category: dict[str, list[dict[str, Any]]] = {}
        if not make_list_data:
            return

        roles = make_list_data.get("column_roles") or {}
        material_keys = list(roles.get("material_keys") or [])
        make_keys = list(roles.get("make_keys") or [])

        # Prefer explicit category_mappings (AI/heuristic). Fall back to row fields.
        mappings = list(make_list_data.get("category_mappings") or [])
        if mappings:
            for item in mappings:
                description = str(item.get("material") or "").strip()
                approved = item.get("approved_makes_list") or []
                category = str(item.get("mapped_category") or "").strip()
                if not description or not approved:
                    continue
                entry = {
                    "description": description,
                    "tokens": _token_set(description),
                    "approved_makes_list": [_normalize_make(m) for m in approved],
                    "mapped_category": category or None,
                    "mapped_sub_category": str(item.get("mapped_sub_category") or "").strip() or None,
                    "confidence": item.get("confidence"),
                }
                self._entries.append(entry)
                if category:
                    key = _normalize_text(category)
                    self._by_category.setdefault(key, []).append(entry)
            return

        tree = make_list_data.get("rows_tree") or []
        nodes = walk_rows_tree(tree) if tree else []
        if not nodes:
            # Flat rows path (before structure_for_analysis).
            nodes = [
                {
                    "fields": row.get("display_values") or row.get("values") or {},
                    "approved_makes_list": row.get("approved_makes_list") or [],
                    "mapped_category": row.get("mapped_category"),
                    "mapped_sub_category": row.get("mapped_sub_category"),
                }
                for row in (make_list_data.get("rows") or [])
            ]

        for node in nodes:
            fields = node.get("fields") or {}
            description = _description_from_fields(
                fields,
                material_keys=material_keys,
                make_keys=make_keys,
            )
            approved = node.get("approved_makes_list") or []
            category = str(node.get("mapped_category") or fields.get("mapped_category") or "").strip()
            if description and approved:
                entry = {
                    "description": description,
                    "tokens": _token_set(description),
                    "approved_makes_list": [_normalize_make(m) for m in approved],
                    "mapped_category": category or None,
                    "mapped_sub_category": str(
                        node.get("mapped_sub_category") or fields.get("mapped_sub_category") or ""
                    ).strip()
                    or None,
                    "confidence": node.get("category_mapping_confidence"),
                }
                self._entries.append(entry)
                if category:
                    key = _normalize_text(category)
                    self._by_category.setdefault(key, []).append(entry)

    @property
    def has_constraints(self) -> bool:
        return bool(self._entries)

    def all_approved_makes(self) -> list[str]:
        """Return every approved make from the indexed make list."""
        makes: list[str] = []
        for entry in self._entries:
            for make in entry.get("approved_makes_list") or []:
                if make not in makes:
                    makes.append(make)
        return makes

    def approved_makes_for_category(
        self,
        category: str,
        sub_category: str = "",
    ) -> list[str] | None:
        """Return approved makes mapped to this Rate_Master / product category."""
        if not category or not self._entries:
            return None

        category_norm = _normalize_text(category)
        sub_norm = _normalize_text(sub_category)
        matched_entries: list[dict[str, Any]] = []

        for key, entries in self._by_category.items():
            if _categories_equivalent(key, category_norm):
                matched_entries.extend(entries)

        if not matched_entries:
            # Soft fallback: category tokens vs make-list description.
            for entry in self._entries:
                mapped = entry.get("mapped_category") or ""
                if mapped and _categories_equivalent(mapped, category):
                    matched_entries.append(entry)
                    continue
                if category_norm and (category_norm in _normalize_text(entry["description"])):
                    matched_entries.append(entry)

        if not matched_entries:
            return None

        if sub_norm:
            sub_hits = [
                entry
                for entry in matched_entries
                if _normalize_text(str(entry.get("mapped_sub_category") or "")) == sub_norm
                or sub_norm in _normalize_text(entry["description"])
            ]
            if sub_hits:
                matched_entries = sub_hits

        makes: list[str] = []
        for entry in matched_entries:
            for make in entry.get("approved_makes_list") or []:
                if make not in makes:
                    makes.append(make)
        return makes or None

    def approved_makes_for_description(self, description: str) -> list[str] | None:
        """Return approved makes when a make-list line matches the BOQ description."""
        matched = self.match_for_description(description)
        if not matched:
            return None
        return list(matched.get("approved_makes") or []) or None

    def match_for_description(self, description: str) -> dict[str, Any] | None:
        """Return make-list match metadata for a BOQ line description."""
        if not self._entries or not description:
            return None

        query_tokens = _token_set(description)
        if not query_tokens:
            return None

        best_score = 0.0
        best_entry: dict[str, Any] | None = None
        for entry in self._entries:
            overlap = query_tokens & entry["tokens"]
            if not overlap:
                continue
            score = len(overlap) / max(len(query_tokens), 1)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_score < 0.25 or not best_entry:
            return None

        return {
            "material": best_entry["description"],
            "approved_makes": list(best_entry["approved_makes_list"]),
            "match_score": round(best_score, 2),
            "mapped_category": best_entry.get("mapped_category"),
            "mapped_sub_category": best_entry.get("mapped_sub_category"),
        }

    def make_options_for_product(
        self,
        *,
        category: str = "",
        sub_category: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        """Return make-list options preferring category mapping, then description match."""
        matched = self.match_for_description(description)
        category_makes = self.approved_makes_for_category(category, sub_category) or []

        make_options: list[str] = []
        # Category-mapped makes first (primary selection path).
        for make in category_makes:
            if make not in make_options:
                make_options.append(make)
        for make in (matched or {}).get("approved_makes") or []:
            if make not in make_options:
                make_options.append(make)

        category_material = ""
        if category:
            for entry in self._entries:
                mapped = entry.get("mapped_category") or ""
                if mapped and _categories_equivalent(mapped, category):
                    category_material = entry["description"]
                    break

        material = (matched or {}).get("material") or category_material or ""
        return {
            "matched": bool(matched) or bool(category_makes),
            "material": material,
            "approved_makes": make_options,
            "make_options": make_options,
            "match_score": (matched or {}).get("match_score"),
            "category_material": category_material,
            "mapped_category": category or (matched or {}).get("mapped_category") or "",
            "selection_basis": (
                "category"
                if category_makes
                else ("description" if matched else "none")
            ),
        }

    @staticmethod
    def is_lowest_make_selection(value: str | None) -> bool:
        text = _normalize_make(str(value or ""))
        return text in {
            _normalize_make(LOWEST_MAKE_VALUE),
            _normalize_make(LOWEST_MAKE_STORED),
            "LOWEST MAKE",
            "LOWEST PRICE",
        }

    @staticmethod
    def make_is_allowed(make_value: str | None, approved_makes: list[str] | None) -> bool:
        if not approved_makes:
            return True
        normalized = _normalize_make(str(make_value or ""))
        if not normalized:
            return False
        return normalized in approved_makes

    @staticmethod
    def filter_rate_ids_by_make(
        rate_rows: list[Any],
        approved_makes: list[str] | None,
    ) -> list[Any]:
        """Hard filter: keep only rows whose Make is in the approved list."""
        if not approved_makes:
            return rate_rows
        filtered = [
            row for row in rate_rows if MakeListConstraintService.make_is_allowed(row.Make, approved_makes)
        ]
        return filtered
