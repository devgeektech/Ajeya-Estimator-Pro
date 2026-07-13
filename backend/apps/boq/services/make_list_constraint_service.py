"""Index make-list approved makes and apply hard filters during matching."""
from __future__ import annotations

import re
from typing import Any, Iterable

_DESCRIPTION_KEYS = (
    "description",
    "item_description",
    "particulars",
    "item",
    "material",
    "name",
)


def _normalize_make(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().upper())


def _normalize_text(value: str) -> str:
    text = re.sub(r"[^0-9a-zA-Z]+", " ", (value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _token_set(text: str) -> set[str]:
    return {token for token in _normalize_text(text).split() if len(token) > 2}


def _description_from_fields(fields: dict[str, Any]) -> str:
    for key in _DESCRIPTION_KEYS:
        value = fields.get(key)
        if value not in (None, ""):
            return str(value).strip()
    for value in fields.values():
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
    """Map BOQ descriptions to approved makes from the make list."""

    def __init__(self, make_list_data: dict | None):
        self._entries: list[dict[str, Any]] = []
        if not make_list_data:
            return
        tree = make_list_data.get("rows_tree") or []
        for node in walk_rows_tree(tree):
            fields = node.get("fields") or {}
            description = _description_from_fields(fields)
            approved = node.get("approved_makes_list") or []
            if description and approved:
                self._entries.append(
                    {
                        "description": description,
                        "tokens": _token_set(description),
                        "approved_makes_list": [_normalize_make(m) for m in approved],
                    }
                )

    @property
    def has_constraints(self) -> bool:
        return bool(self._entries)

    def approved_makes_for_description(self, description: str) -> list[str] | None:
        """Return approved makes when a make-list line matches the BOQ description."""
        if not self._entries or not description:
            return None

        query_tokens = _token_set(description)
        if not query_tokens:
            return None

        best_score = 0.0
        best_makes: list[str] | None = None
        for entry in self._entries:
            overlap = query_tokens & entry["tokens"]
            if not overlap:
                continue
            score = len(overlap) / max(len(query_tokens), 1)
            if score > best_score:
                best_score = score
                best_makes = entry["approved_makes_list"]

        if best_score >= 0.25 and best_makes:
            return best_makes
        return None

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
