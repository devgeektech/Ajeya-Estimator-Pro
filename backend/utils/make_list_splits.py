"""Detect make-list columns heuristically and split approved makes."""
from __future__ import annotations

import re
from typing import Any

# Common make-list separators: TATA/JINDAL, A, B, C, A; B | C
_MAKE_SPLIT_PATTERN = re.compile(r"\s*[/;,|]\s*")
_SERIAL_KEY_HINTS = frozenset(
    {
        "s_no",
        "sno",
        "sl_no",
        "sr_no",
        "serial",
        "serial_no",
        "item_no",
        "no",
        "sr",
    }
)

# Header tokens that strongly suggest a make/manufacturer column.
_MAKE_HEADER_STRONG = (
    "approved_make",
    "approved_makes",
    "manufacturer",
    "manufacturers",
    "make_name",
    "makes",
    "brand",
    "brands",
    "vendor",
)

# Header tokens that strongly suggest material / description (not makes).
_MATERIAL_HEADER_STRONG = (
    "material",
    "materials",
    "description",
    "particular",
    "particulars",
    "item_description",
    "product",
    "category",
    "type_of",
)

_WEAK_NAME_KEYS = frozenset({"name", "names", "title"})


def split_make_token(value: Any) -> list[str]:
    """Split one cell value into make tokens (e.g. ``TATA/JINDAL/SURYA``)."""
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in _MAKE_SPLIT_PATTERN.split(text) if part.strip()]


def _norm_key(key: Any) -> str:
    return str(key or "").strip().lower()


def _header_blob(key: str, label: str = "") -> str:
    return f"{_norm_key(key)} {_norm_key(label)}".strip()


def _is_serial_key(key: str) -> bool:
    key_text = _norm_key(key)
    if key_text in _SERIAL_KEY_HINTS:
        return True
    return any(hint in key_text for hint in ("s_no", "sl_no", "serial", "sr_no"))


def _looks_like_make_list_text(value: Any) -> bool:
    """True when a cell looks like one or more manufacturer names."""
    if value is None:
        return False
    text = str(value).strip()
    if not text or len(text) > 120:
        return False
    tokens = split_make_token(text)
    if len(tokens) >= 2:
        # Slash/comma lists are the strongest make-list signal.
        return all(1 <= len(token.split()) <= 4 for token in tokens)
    words = text.split()
    if len(words) > 6:
        return False
    # Single short brand-like values (e.g. "Jaquar", "ESS ESS").
    return 1 <= len(words) <= 3 and not any(ch.isdigit() for ch in text)


def _looks_like_material_text(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if len(split_make_token(text)) >= 3:
        return False
    words = text.split()
    return len(text) >= 18 or len(words) >= 4


# Columns that must never be treated as make sources.
_MAKE_EXCLUDE_HINTS = (
    "rate",
    "amount",
    "qty",
    "quantity",
    "unit",
    "uom",
    "discount",
    "price",
    "cost",
    "dia",
    "mm",
    "column_",
    "remark",
    "ref_to",
    "page",
    "sub_head",
    "packing",
    "freight",
    "contractor",
    "overhead",
    "excise",
    "wastage",
    "installation",
    "signage",
    "increase",
)


def is_excluded_make_key(key: str, label: str = "") -> bool:
    """True when a column must not be treated as an approved-makes source."""
    blob = _header_blob(key, label)
    key_text = _norm_key(key)
    if key_text.startswith("column_") or key_text.isdigit():
        return True
    if key_text.startswith("approved_makes"):
        return False
    if "make" in blob or "manufacturer" in blob or "brand" in blob:
        return False
    return any(hint in blob for hint in _MAKE_EXCLUDE_HINTS)


# Backward-compatible private alias.
_is_excluded_make_key = is_excluded_make_key


def score_make_header(key: str, label: str = "") -> int:
    """Score how likely a header is the approved-makes column."""
    blob = _header_blob(key, label)
    key_text = _norm_key(key)
    if not blob or _is_serial_key(key_text):
        return -100
    if _is_excluded_make_key(key, label):
        return -100
    score = 0
    if key_text == "make" or blob == "make":
        score += 40
    if key_text.startswith("approved_makes"):
        score += 50
    if any(token in blob for token in _MAKE_HEADER_STRONG):
        score += 35
    if "make" in blob:
        score += 25
    if key_text in _WEAK_NAME_KEYS or blob in _WEAK_NAME_KEYS:
        # Ambiguous alone — content scoring decides.
        score += 8
    if any(token in blob for token in _MATERIAL_HEADER_STRONG) and "make" not in blob:
        score -= 40
    if "material" in blob and "make" not in blob:
        score -= 50
    return score


def score_material_header(key: str, label: str = "") -> int:
    """Score how likely a header is the material/description column."""
    blob = _header_blob(key, label)
    key_text = _norm_key(key)
    if not blob or _is_serial_key(key_text):
        return -100
    score = 0
    if any(token in blob for token in _MATERIAL_HEADER_STRONG):
        score += 35
    if "description" in blob or "material" in blob or "particular" in blob:
        score += 20
    if key_text in _WEAK_NAME_KEYS:
        score += 5
    if "make" in blob or any(token in blob for token in _MAKE_HEADER_STRONG):
        score -= 40
    return score


def _column_values(rows: list[dict], key: str, *, limit: int = 40) -> list[Any]:
    values: list[Any] = []
    for row in rows:
        source = row.get("display_values") or row.get("values") or {}
        value = source.get(key)
        if value is None or str(value).strip() == "":
            continue
        values.append(value)
        if len(values) >= limit:
            break
    return values


def _content_make_score(values: list[Any]) -> float:
    if not values:
        return 0.0
    hits = sum(1 for value in values if _looks_like_make_list_text(value))
    return hits / len(values)


def _content_material_score(values: list[Any]) -> float:
    if not values:
        return 0.0
    hits = sum(1 for value in values if _looks_like_material_text(value))
    return hits / len(values)


def _candidate_keys(rows: list[dict], headers: list[dict] | None) -> list[tuple[str, str]]:
    """Return ``(key, label)`` candidates from headers or row value maps."""
    if headers:
        return [
            (str(header.get("key") or ""), str(header.get("label") or ""))
            for header in headers
            if header.get("key")
        ]
    keys: set[str] = set()
    for row in rows[:20]:
        source = row.get("display_values") or row.get("values") or {}
        keys.update(str(key) for key in source.keys())
    return [(key, key) for key in sorted(keys)]


def resolve_make_list_columns(
    rows: list[dict],
    headers: list[dict] | None = None,
) -> dict[str, list[str]]:
    """
    Infer material vs make columns from headers + cell content.

    Works when headers are ``Material`` / ``Make``, ``Description`` / ``Name``,
    ``Make/Manufacturers Name``, or other unknown variants.
    """
    candidates = _candidate_keys(rows, headers)
    make_ranked: list[tuple[float, str]] = []
    material_ranked: list[tuple[float, str]] = []

    for key, label in candidates:
        key_text = _norm_key(key)
        if not key_text or _is_serial_key(key_text):
            continue
        if _is_excluded_make_key(key, label) and not key_text.startswith("approved_makes"):
            # Still allow material scoring for description columns.
            material_score = score_material_header(key, label) + (
                40.0 * _content_material_score(_column_values(rows, key))
            )
            material_ranked.append((material_score, key))
            continue
        values = _column_values(rows, key)
        make_score = score_make_header(key, label) + (40.0 * _content_make_score(values))
        material_score = score_material_header(key, label) + (
            40.0 * _content_material_score(values)
        )
        make_ranked.append((make_score, key))
        material_ranked.append((material_score, key))

    make_ranked.sort(reverse=True)
    material_ranked.sort(reverse=True)

    make_keys: list[str] = []
    for score, key in make_ranked:
        if score < 25:
            break
        # Prefer explicit make/approved columns; allow multiple approved_makes_*.
        key_text = _norm_key(key)
        strong = (
            key_text.startswith("approved_makes")
            or "make" in key_text
            or "manufacturer" in key_text
            or "brand" in key_text
            or score >= 40
        )
        if strong or (not make_keys and score >= 25):
            make_keys.append(key)

    material_keys: list[str] = []
    for score, key in material_ranked:
        if score < 10:
            break
        if key in make_keys:
            continue
        material_keys.append(key)
        break

    # Fallback: best content-only make column if headers were useless.
    if not make_keys and make_ranked:
        best_score, best_key = make_ranked[0]
        values = _column_values(rows, best_key)
        if best_score >= 8 or _content_make_score(values) >= 0.35:
            make_keys = [best_key]

    if not material_keys and material_ranked:
        for _score, key in material_ranked:
            if key not in make_keys:
                material_keys = [key]
                break

    return {
        "make_keys": make_keys,
        "material_keys": material_keys,
    }


def is_make_column_key(key: Any, *, make_keys: list[str] | None = None) -> bool:
    """Backward-compatible check; prefers resolved ``make_keys`` when provided."""
    key_text = _norm_key(key)
    if not key_text:
        return False
    if make_keys is not None:
        return key_text in {_norm_key(item) for item in make_keys} or key in make_keys
    return score_make_header(key_text) >= 20


def collect_approved_makes(
    row: dict,
    *,
    make_keys: list[str] | None = None,
) -> list[str]:
    """Collect de-duplicated approved makes from resolved make columns."""
    source = row.get("display_values") or row.get("values") or {}
    keys = list(make_keys or [])
    if not keys:
        keys = resolve_make_list_columns([row]).get("make_keys") or []
        if not keys:
            # Last resort: any column whose header alone looks like makes.
            keys = [key for key in source if score_make_header(str(key)) >= 20]

    # Keep approved_makes, approved_makes_2… in column order (not score order).
    def _make_key_order(key: str) -> tuple[int, int | str]:
        match = re.match(r"^approved_makes(?:_(\d+))?$", _norm_key(key))
        if match:
            return (0, int(match.group(1) or 1))
        try:
            return (1, keys.index(key))
        except ValueError:
            return (2, _norm_key(key))

    keys = sorted(keys, key=_make_key_order)

    makes: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for token in split_make_token(source.get(key)):
            fold = token.casefold()
            if fold in seen:
                continue
            seen.add(fold)
            makes.append(token)
    # Prefer parser-attached list when present and complete.
    existing = row.get("approved_makes_list")
    if isinstance(existing, list) and existing and len(existing) >= len(makes):
        return [str(item).strip() for item in existing if str(item).strip()]
    return makes


# Bump when description/make peel rules change so stored JSON is re-repaired.
MAKE_LIST_SPLIT_REPAIR_VERSION = 2


def approved_makes_column_keys(count: int) -> list[str]:
    """Return ``approved_makes`` / ``approved_makes_2`` … keys for ``count`` makes.

    There is **no fixed cap** — count may be 1, 4, 6, 10, ….
    """
    size = max(1, int(count or 0))
    keys = ["approved_makes"]
    for index in range(2, size + 1):
        keys.append(f"approved_makes_{index}")
    return keys


def _material_key_for_row(
    row: dict,
    *,
    material_keys: list[str] | None = None,
) -> str:
    display = row.get("display_values") or row.get("values") or {}
    for key in (*(material_keys or ()), "description", "material", "particulars", "desc"):
        if key and isinstance(display, dict) and display.get(key) not in (None, ""):
            return str(key)
    return "description"


def _write_makes_into_columns(
    display: dict[str, Any],
    values: dict[str, Any],
    makes: list[str],
    *,
    make_keys: list[str],
) -> list[str]:
    """Mirror approved makes into display/values make columns for UI consistency.

    Expands ``approved_makes_N`` columns when ``makes`` is longer than ``make_keys``.
    Returns the keys actually written (no fixed cap).
    """
    needed = max(len(makes), len([k for k in (make_keys or []) if str(k).startswith("approved_makes")]), 1)
    keys = approved_makes_column_keys(needed)
    for index, key in enumerate(keys):
        value = makes[index] if index < len(makes) else None
        display[key] = value
        values[key] = value
    keep = set(keys)
    for key in list(display.keys()):
        if str(key).startswith("approved_makes") and key not in keep:
            display.pop(key, None)
            values.pop(key, None)
    return keys


def expand_payload_make_columns(payload: dict | None) -> dict:
    """Ensure headers / make_keys cover every entry in ``approved_makes_list``.

    Source of truth is ``approved_makes_list`` (unlimited). Per-make columns are
    only mirrors for Excel-like layouts and grow to the longest row.
    """
    if not payload:
        return {}
    rows = list(payload.get("rows") or [])
    max_makes = max(
        (len(row.get("approved_makes_list") or []) for row in rows),
        default=0,
    )
    roles = dict(payload.get("column_roles") or {})
    existing_make_keys = list(roles.get("make_keys") or [])
    # Keep non-approved Excel make columns (e.g. ``make``) and always ensure
    # approved_makes_* mirrors cover the longest list.
    extra_keys = [
        key for key in existing_make_keys if not str(key).startswith("approved_makes")
    ]
    make_keys = extra_keys + [
        key
        for key in approved_makes_column_keys(max(max_makes, 1))
        if key not in extra_keys
    ]

    material_keys = list(roles.get("material_keys") or [])
    updated_rows: list[dict] = []
    for row in rows:
        makes = [
            str(item).strip()
            for item in (row.get("approved_makes_list") or [])
            if str(item).strip()
        ]
        display = dict(row.get("display_values") or {})
        values = dict(row.get("values") or {})
        _write_makes_into_columns(
            display,
            values,
            makes,
            make_keys=make_keys,
        )
        updated_rows.append(
            {
                **row,
                "display_values": display,
                "values": values,
                "approved_makes_list": makes,
            }
        )

    header_by_key = {
        str(header.get("key")): header for header in (payload.get("headers") or [])
    }
    serial_key = payload.get("serial_key")
    material_key = (material_keys[0] if material_keys else None) or "description"
    ordered_keys: list[str] = []
    for key in (serial_key, material_key, *make_keys):
        if key and key not in ordered_keys:
            ordered_keys.append(str(key))

    headers: list[dict] = []
    for index, key in enumerate(ordered_keys):
        existing = header_by_key.get(key)
        if existing:
            headers.append({**existing, "index": index})
            continue
        if key == "approved_makes":
            label = "Approved Makes"
        elif str(key).startswith("approved_makes_"):
            suffix = str(key).removeprefix("approved_makes_")
            label = f"Approved Makes {suffix}"
        else:
            label = str(key).replace("_", " ").title()
        headers.append({"key": key, "label": label, "index": index})

    enriched = dict(payload)
    enriched["rows"] = updated_rows
    enriched["headers"] = headers
    enriched["column_roles"] = {
        **roles,
        "make_keys": [key for key in make_keys if str(key).startswith("approved_makes")]
        or make_keys,
        "material_keys": material_keys or [material_key],
    }
    return enriched


def repair_make_list_row_split(
    row: dict,
    *,
    material_keys: list[str] | None = None,
    make_keys: list[str] | None = None,
) -> dict:
    """
    Move material nouns wrongly captured in ``approved_makes_list`` back into
    the description (e.g. ``Drums SAFEGUARD`` → description gains ``Drums``).
    """
    if row.get("is_section_heading"):
        return row

    from utils.text_boundary import repair_description_and_makes

    material_key = _material_key_for_row(row, material_keys=material_keys)
    display = dict(row.get("display_values") or {})
    values = dict(row.get("values") or {})
    description = str(display.get(material_key) or values.get(material_key) or "").strip()
    makes = [str(item).strip() for item in (row.get("approved_makes_list") or []) if str(item).strip()]
    if not description and not makes:
        return row

    new_description, new_makes = repair_description_and_makes(description, makes)
    if new_description == description and new_makes == makes:
        return row

    display[material_key] = new_description or None
    values[material_key] = new_description or None
    _write_makes_into_columns(
        display,
        values,
        new_makes,
        make_keys=list(make_keys or []),
    )
    return {
        **row,
        "display_values": display,
        "values": values,
        "approved_makes_list": new_makes,
    }


def repair_make_list_payload_splits(payload: dict | None) -> dict:
    """Repair description/make peel mistakes on every make-list row."""
    if not payload:
        return {}
    roles = payload.get("column_roles") or {}
    material_keys = list(roles.get("material_keys") or [])
    make_keys = list(roles.get("make_keys") or [])
    rows = [
        repair_make_list_row_split(
            row,
            material_keys=material_keys,
            make_keys=make_keys,
        )
        for row in (payload.get("rows") or [])
    ]
    enriched = dict(payload)
    enriched["rows"] = rows
    enriched["split_repair_version"] = MAKE_LIST_SPLIT_REPAIR_VERSION
    # Grow approved_makes_N columns to the longest approved_makes_list (no cap).
    return expand_payload_make_columns(enriched)


def attach_approved_makes_list(
    rows: list[dict],
    headers: list[dict] | None = None,
) -> tuple[list[dict], dict[str, list[str]]]:
    """Attach ``approved_makes_list`` using heuristically resolved columns."""
    roles = resolve_make_list_columns(rows, headers=headers)
    make_keys = roles.get("make_keys") or []
    material_keys = roles.get("material_keys") or []
    enriched: list[dict] = []
    for row in rows:
        existing = row.get("approved_makes_list")
        if isinstance(existing, list) and any(str(item).strip() for item in existing):
            approved_makes_list = [str(item).strip() for item in existing if str(item).strip()]
        else:
            approved_makes_list = collect_approved_makes(row, make_keys=make_keys)
        repaired = repair_make_list_row_split(
            {**row, "approved_makes_list": approved_makes_list},
            material_keys=material_keys,
            make_keys=make_keys,
        )
        enriched.append(repaired)
    return enriched, roles


def row_has_make_source(
    row: dict,
    *,
    make_keys: list[str] | None = None,
) -> bool:
    """True when the row has a make-column value that can be split."""
    source = row.get("display_values") or row.get("values") or {}
    keys = make_keys
    if keys is None:
        keys = [
            key
            for key in source
            if score_make_header(str(key)) >= 8 or _looks_like_make_list_text(source.get(key))
        ]
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return True
    return False
