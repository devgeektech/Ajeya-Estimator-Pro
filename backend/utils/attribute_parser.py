"""Parse and normalize dynamic Rate_Master Attribute strings."""
from __future__ import annotations

import re
from typing import Any

_TOKEN_SPLIT = re.compile(r"[;,]")
_PAIR_SPLIT = re.compile(r"=")
_KEY_NORMALIZE = re.compile(r"[^0-9a-zA-Z]+")

# Seed synonyms/aliases → canonical DB-style keys. Grows via learn_aliases_from_attributes.
DEFAULT_KEY_ALIASES: dict[str, str] = {
    # Standards
    "standard": "is",
    "hose_standard": "is",
    "is_standard": "is",
    "is_no": "is",
    "is": "is",
    # Outlet / connection
    "outlet": "outlet_type",
    "outlet_type": "outlet_type",
    "outlet_size": "outlet_size",
    "connection": "connection_type",
    "connection_type": "connection_type",
    "end_connection": "connection_type",
    # Type / port / valve style
    "valve_type": "type",
    "door_type": "type",
    "leaf_type": "type",
    "port_type": "type",
    "port": "type",
    "full_port": "type",
    "type": "type",
    # Material
    "material": "material",
    "body_material": "material",
    "construction": "material",
    # Mounting
    "mounting": "mounting",
    "mount": "mounting",
    "installation": "mounting",
    # Pressure
    "pressure_rating": "pressure_rating",
    "pressure": "pressure_rating",
    "working_pressure": "pressure_rating",
    "min_working_pressure": "pressure_rating",
    "minimum_working_pressure": "pressure_rating",
    "max_working_pressure": "pressure_rating",
    "maximum_working_pressure": "pressure_rating",
    "pn": "pressure_rating",
    "pn_rating": "pressure_rating",
    # Fire / seat / operation
    "fire_rating": "fire_rating",
    "operation": "operation",
    "operated": "operation",
    "seat_type": "seat_type",
    "seat": "seat_type",
    "vision_panel": "vision_panel",
    # Size-like attrs sometimes stored in Attribute
    "nb": "size",
    "nominal_bore": "size",
    "dia": "size",
    "diameter": "size",
}


def normalize_attribute_key(key: str, aliases: dict[str, str] | None = None) -> str:
    cleaned = _KEY_NORMALIZE.sub("_", (key or "").strip().lower()).strip("_")
    alias_map = aliases or DEFAULT_KEY_ALIASES
    return alias_map.get(cleaned, cleaned)


# Value-level synonyms for material / construction abbreviations.
DEFAULT_VALUE_ALIASES: dict[str, str] = {
    "ms": "mild steel",
    "m.s": "mild steel",
    "m.s.": "mild steel",
    "di": "ductile iron",
    "d.i": "ductile iron",
    "d.i.": "ductile iron",
    "ci": "cast iron",
    "c.i": "cast iron",
    "c.i.": "cast iron",
    "gi": "galvanised iron",
    "g.i": "galvanised iron",
    "g.i.": "galvanised iron",
    "ss": "stainless steel",
    "s.s": "stainless steel",
    "s.s.": "stainless steel",
    "cs": "carbon steel",
    "c.s": "carbon steel",
    "c.s.": "carbon steel",
    "fullway": "full port",
    "full way": "full port",
}


def normalize_attribute_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return text
    # Exact abbreviation match.
    compact = text.replace(".", "")
    if text in DEFAULT_VALUE_ALIASES:
        return DEFAULT_VALUE_ALIASES[text]
    if compact in DEFAULT_VALUE_ALIASES:
        return DEFAULT_VALUE_ALIASES[compact]
    # Token-wise expansion (e.g. "MS pipe" → "mild steel pipe").
    tokens = text.split(" ")
    expanded: list[str] = []
    for token in tokens:
        token_compact = token.replace(".", "")
        expanded.append(
            DEFAULT_VALUE_ALIASES.get(token)
            or DEFAULT_VALUE_ALIASES.get(token_compact)
            or token
        )
    return " ".join(expanded)


def build_alias_map(
    schema_keys: list[str] | None = None,
    *,
    extra_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge seed synonyms with schema keys and optional runtime aliases."""
    aliases = dict(DEFAULT_KEY_ALIASES)
    if extra_aliases:
        aliases.update(extra_aliases)
    for key in schema_keys or []:
        key_text = str(key or "").strip()
        if not key_text:
            continue
        cleaned = _KEY_NORMALIZE.sub("_", key_text.lower()).strip("_")
        aliases.setdefault(cleaned, key_text)
        aliases.setdefault(key_text, key_text)
    return aliases


def resolve_to_schema_key(
    extracted_key: str,
    schema_keys: list[str],
    *,
    aliases: dict[str, str] | None = None,
) -> str | None:
    """
    Map an extracted attribute key onto a DB schema key using synonyms.

    Examples: ``port_type`` → ``type``, ``minimum_working_pressure`` → ``pressure_rating``.
    """
    if not schema_keys:
        return None
    alias_map = aliases or build_alias_map(schema_keys)
    schema_set = {str(key) for key in schema_keys}
    cleaned = _KEY_NORMALIZE.sub("_", (extracted_key or "").strip().lower()).strip("_")
    if not cleaned:
        return None
    if cleaned in schema_set:
        return cleaned
    if extracted_key in schema_set:
        return str(extracted_key)

    canonical = normalize_attribute_key(cleaned, aliases=alias_map)
    if canonical in schema_set:
        return canonical

    for schema_key in schema_keys:
        schema_canon = normalize_attribute_key(str(schema_key), aliases=alias_map)
        if schema_canon == canonical or schema_canon == cleaned:
            return str(schema_key)
        # Soft contain match for long synonym phrases.
        schema_clean = _KEY_NORMALIZE.sub("_", str(schema_key).lower()).strip("_")
        if cleaned and schema_clean and (cleaned in schema_clean or schema_clean in cleaned):
            return str(schema_key)
    return None


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
    """Score overlap between two normalized attribute dicts (synonym-aware keys)."""
    if not extracted:
        return 1.0, {}
    if not candidate:
        return 0.0, {}

    alias_map = build_alias_map(list(candidate.keys()))
    candidate_by_canon = {
        normalize_attribute_key(str(key), aliases=alias_map): value
        for key, value in candidate.items()
    }

    scores: dict[str, float] = {}
    matched = 0.0
    for key, extracted_value in extracted.items():
        schema_key = resolve_to_schema_key(str(key), list(candidate.keys()), aliases=alias_map)
        candidate_value = candidate.get(schema_key) if schema_key else None
        if candidate_value is None:
            canon = normalize_attribute_key(str(key), aliases=alias_map)
            candidate_value = candidate_by_canon.get(canon)
        if candidate_value is None:
            continue
        score_key = schema_key or str(key)
        if _values_match(extracted_value, candidate_value):
            scores[score_key] = 1.0
            matched += 1.0
        elif _partial_value_match(extracted_value, candidate_value):
            scores[score_key] = 0.6
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


def _parse_attribute_blob(raw: Any) -> dict[str, Any] | None:
    """Parse a nested attributes object or stringified dict/JSON blob."""
    import ast
    import json

    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or text[0] not in "{[":
        return None
    # Prefer JSON; fall back to Python-literal style from str(dict).
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, dict) else None
    except (SyntaxError, ValueError):
        return None


def coerce_attributes_dict(raw: Any) -> dict[str, str]:
    """
    Flatten AI attribute payloads into ``{key: value}`` strings.

    Handles nested dicts and stringified blobs such as
    ``\"attributes\": \"{'material': 'mild steel'}\"`` that otherwise render as
    raw Python dict text in the UI.
    """
    if not raw:
        return {}

    if isinstance(raw, str):
        parsed = _parse_attribute_blob(raw)
        if parsed is None:
            return {}
        raw = parsed
    if not isinstance(raw, dict):
        return {}

    flattened: dict[str, str] = {}

    def _absorb(source: dict[str, Any]) -> None:
        for key, value in source.items():
            key_text = normalize_attribute_key(str(key or ""))
            if not key_text:
                continue
            # Nested / stringified attribute bags — unwrap instead of str(dict).
            if key_text in {"attributes", "attribute", "attrs"} or isinstance(value, dict):
                nested = _parse_attribute_blob(value)
                if nested is not None:
                    _absorb(nested)
                    continue
            if value is None:
                continue
            value_text = str(value).strip()
            if not value_text or value_text in {"{}", "[]", "null", "None"}:
                continue
            # Skip leftover stringified dicts that failed to parse.
            if value_text[0] in "{[" and _parse_attribute_blob(value_text) is not None:
                continue
            flattened.setdefault(key_text, normalize_attribute_value(value_text) or value_text)

    _absorb(raw)
    return flattened
