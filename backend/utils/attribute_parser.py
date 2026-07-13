"""Parse and normalize dynamic Rate_Master Attribute strings."""
from __future__ import annotations

import re
from typing import Any

_TOKEN_SPLIT = re.compile(r"[;,]")
_PAIR_SPLIT = re.compile(r"=")
_KEY_NORMALIZE = re.compile(r"[^0-9a-zA-Z]+")

# Seed aliases; grows as new keys are seen in the active database.
DEFAULT_KEY_ALIASES: dict[str, str] = {
    "standard": "is",
    "hose_standard": "is",
    "is": "is",
    "outlet": "outlet_type",
    "outlet_type": "outlet_type",
    "outlet_size": "outlet_size",
    "valve_type": "type",
    "door_type": "type",
    "leaf_type": "type",
    "port_type": "type",
    "type": "type",
    "material": "material",
    "mounting": "mounting",
    "connection": "connection_type",
    "connection_type": "connection_type",
    "pressure_rating": "pressure_rating",
    "fire_rating": "fire_rating",
    "operation": "operation",
    "seat_type": "seat_type",
    "vision_panel": "vision_panel",
}


def normalize_attribute_key(key: str, aliases: dict[str, str] | None = None) -> str:
    cleaned = _KEY_NORMALIZE.sub("_", (key or "").strip().lower()).strip("_")
    alias_map = aliases or DEFAULT_KEY_ALIASES
    return alias_map.get(cleaned, cleaned)


def normalize_attribute_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def parse_attributes(
    raw: str | None,
    *,
    aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    """Parse ``Mounting=Pillar; IS=5290`` style text into a normalized dict."""
    if not raw or not str(raw).strip():
        return {}

    attributes: dict[str, str] = {}
    for token in _TOKEN_SPLIT.split(str(raw)):
        piece = token.strip()
        if not piece or "=" not in piece:
            continue
        key_text, value_text = piece.split("=", 1)
        key = normalize_attribute_key(key_text, aliases=aliases)
        value = normalize_attribute_value(value_text)
        if key and value:
            attributes[key] = value
    return attributes


def learn_aliases_from_attributes(
  attributes: dict[str, str],
  aliases: dict[str, str],
) -> None:
    """Record unseen attribute keys (identity mapping) for future normalization."""
    for key in attributes:
        aliases.setdefault(key, key)


def attribute_overlap_score(
    extracted: dict[str, str],
    candidate: dict[str, str],
) -> tuple[float, dict[str, float]]:
    """Score overlap between two normalized attribute dicts."""
    if not extracted:
        return 1.0, {}
    if not candidate:
        return 0.0, {}

    scores: dict[str, float] = {}
    matched = 0.0
    for key, extracted_value in extracted.items():
        candidate_value = candidate.get(key)
        if candidate_value is None:
            continue
        if _values_match(extracted_value, candidate_value):
            scores[key] = 1.0
            matched += 1.0
        elif _partial_value_match(extracted_value, candidate_value):
            scores[key] = 0.6
            matched += 0.6

    return matched / len(extracted), scores


def _values_match(left: str, right: str) -> bool:
    return normalize_attribute_value(left) == normalize_attribute_value(right)


def _partial_value_match(left: str, right: str) -> bool:
    left_digits = re.sub(r"\D", "", left)
    right_digits = re.sub(r"\D", "", right)
    if left_digits and right_digits and left_digits == right_digits:
        return True
    return left in right or right in left
