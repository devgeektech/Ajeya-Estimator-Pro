"""Rate_Master Size / Unit / Capacity patterns — aligned with Product_Helper."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from apps.database_manager.models import Product_Helper
from apps.database_manager.services.activation import get_active_database_version

_SIZE_MEANING: dict[tuple[str, str], str] = {
    ("HYDRANT", "FIRE HOSE"): "hose length (m) — e.g. 15m → size 15, unit m",
    ("HYDRANT", "FIRE HOSE BOX"): "cabinet outer dims → Capacity (e.g. 30X24X10); Size often 0",
    ("HYDRANT", "FIRE HOSE REEL"): "hose bore/outlet (mm) — reel hose length in attributes",
    ("HYDRANT", "BRANCH PIPE"): "nozzle/outlet nominal bore (mm) — e.g. 20mm outlet → size 20, unit mm",
    ("HYDRANT", "SHORT BRANCH PIPE"): "coupling diameter (mm) — nozzle bore in attributes",
    ("HYDRANT", "FIRE DOOR"): "frame dims → Capacity (e.g. 1200 X 2100); Size often 0",
    ("PIPE", "MS"): "nominal pipe diameter (mm dia / NB)",
    ("PIPE", "GI"): "nominal pipe diameter (mm dia / NB)",
    ("VALVE", "SLUICE VALVE"): "nominal valve size (mm / NB); PN → Capacity",
    ("PUMP", "HYDRANT PUMP"): "flow rating → Capacity (lpm); Size often 0",
    ("PUMP", "JOCKEY PUMP"): "flow rating → Capacity (lpm); Size often 0",
    ("EXTINGUISHER", "ABC"): "extinguisher weight (kg)",
    ("EXTINGUISHER", "FOAM"): "extinguisher volume (liter)",
    ("TANK", "GRP WATER TANK"): "tank volume (kl)",
}

_SWG_GAUGE = re.compile(r"(?i)(?<![0-9])(\d+(?:\.\d+)?)\s*swg\b")
_LENGTH_WITH_UNIT = re.compile(
    r"(?i)(?<![0-9])(\d+(?:\.\d+)?)\s*(?:m|metre|meter|mtr)s?\b(?:\s*length)?"
)
_LENGTH_OF_PHRASE = re.compile(
    r"(?i)(?<![0-9])(\d+(?:\.\d+)?)\s*(?:m|metre|meter|mtr)s?\s+length\b"
)
_BOX_DIMENSIONS = re.compile(
    r"(?i)(\d+(?:\.\d+)?)\s*[\"']?\s*[x×]\s*(\d+(?:\.\d+)?)\s*[\"']?\s*[x×]\s*(\d+(?:\.\d+)?)"
)
_NO_NOMINAL_SIZE_SUBS = frozenset(
    {
        "FIRE HOSE BOX",
        "FIRE DOOR",
        "PENDANT",
        "UPRIGHT",
        "SIDE WALL",
        "FIRE MAN AXE",
        "SAND BUCKET SET",
        "FIRE PUMP PANEL",
    }
)
# Longest phrase first — main purchasable product beats contents (branch pipe / hose inside).
_MAIN_PRODUCT_PHRASES: tuple[tuple[str, str, str], ...] = (
    ("external fire hose box", "HYDRANT", "FIRE HOSE BOX"),
    ("fire hose box", "HYDRANT", "FIRE HOSE BOX"),
    ("fire hose cabinet", "HYDRANT", "FIRE HOSE BOX"),
    ("hose cabinet", "HYDRANT", "FIRE HOSE BOX"),
    ("hose box", "HYDRANT", "FIRE HOSE BOX"),
    ("fire hose reel", "HYDRANT", "FIRE HOSE REEL"),
    ("hose reel", "HYDRANT", "FIRE HOSE REEL"),
    ("short branch pipe", "HYDRANT", "SHORT BRANCH PIPE"),
    ("branch pipe", "HYDRANT", "BRANCH PIPE"),
)
_CONTENT_CONTEXT = re.compile(
    r"(?i)\b(?:to accommodate|for accommodating|to house|to store|"
    r"capable of accommodating|hold(?:ing)?|designed to accommodate)\b"
)
_MS_SHEET = re.compile(r"(?i)\bmild\s+steel\b|\bms\s+sheet\b|\bm\.?\s*s\.?\s*sheet\b")


def _normalize_key(category: Any, sub_category: Any) -> tuple[str, str]:
    return (
        str(category or "").strip().upper(),
        str(sub_category or "").strip().upper(),
    )


def load_size_unit_patterns(
    database_version_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Build Size/Unit/Capacity patterns from active Product_Helper rows.

    Each entry: category, sub_category, units[], sample_sizes[], sample_capacities[],
    size_meaning (human hint for AI).
    """
    version = None
    if database_version_id is not None:
        from apps.database_manager.models import DatabaseVersion

        version = DatabaseVersion.objects.filter(pk=database_version_id).first()
    else:
        version = get_active_database_version()

    if version is None:
        return []

    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"units": set(), "sizes": set(), "capacities": set()}
    )
    for helper in Product_Helper.objects.filter(database_version=version).exclude(
        Status__iexact="Discontinued"
    ):
        cat, sub = _normalize_key(helper.Category, helper.Sub_Category)
        if not cat or not sub:
            continue
        bucket = grouped[(cat, sub)]
        unit = str(helper.Unit or "").strip()
        if unit:
            bucket["units"].add(unit)
        if helper.Size is not None:
            size_text = str(helper.Size).strip()
            if size_text:
                bucket["sizes"].add(size_text)
        capacity = str(helper.Capacity or "").strip()
        if capacity and capacity not in {"0", "0.0"}:
            bucket["capacities"].add(capacity)

    patterns: list[dict[str, Any]] = []
    for (cat, sub), bucket in sorted(grouped.items()):
        units = sorted(bucket["units"])
        sizes = sorted(bucket["sizes"], key=lambda value: float(value or 0))[:6]
        capacities = sorted(bucket["capacities"])[:4]
        patterns.append(
            {
                "category": cat,
                "sub_category": sub,
                "units": units,
                "sample_sizes": sizes,
                "sample_capacities": capacities,
                "size_meaning": _SIZE_MEANING.get((cat, sub))
                or _default_size_meaning(units),
            }
        )
    return patterns


def _default_size_meaning(units: list[str]) -> str:
    if not units:
        return "match catalog Unit for this sub-category"
    primary = units[0].lower()
    if primary == "mm":
        return "nominal diameter / bore (mm dia, NB)"
    if primary == "m":
        return "length in metres (e.g. 15m length → size 15, unit m)"
    if primary == "kg":
        return "weight in kg"
    if primary == "liter":
        return "volume in liters"
    if primary == "lpm":
        return "Size often 0; flow rating in Capacity (lpm)"
    if primary == "kl":
        return "tank volume in kiloliters"
    if primary in {"each", "na", "inch"}:
        return f"catalog Unit={primary}; check sample_sizes / sample_capacities"
    return f"catalog Unit={primary}"


def pattern_for_product(
    product: dict[str, Any],
    patterns: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    cat, sub = _normalize_key(product.get("category"), product.get("sub_category"))
    if not cat or not sub:
        return None
    for item in patterns or []:
        if (
            str(item.get("category") or "").upper() == cat
            and str(item.get("sub_category") or "").upper() == sub
        ):
            return item
    return None


def expected_units(pattern: dict[str, Any] | None) -> set[str]:
    if not pattern:
        return set()
    return {
        str(unit).strip().lower()
        for unit in (pattern.get("units") or [])
        if str(unit).strip()
    }


def is_swg_gauge_number(number: str, text: str) -> bool:
    """True when ``number`` is a sheet-gauge token (18 SWG), not nominal size."""
    digits = str(number or "").strip()
    if not digits or not text:
        return False
    return bool(re.search(rf"(?i)(?<![0-9]){re.escape(digits)}\s*swg\b", text))


def parse_length_from_text(text: Any) -> tuple[str | None, str | None]:
    """Return (size, unit=m) from ``15m``, ``15 m length``, etc."""
    blob = str(text or "").strip()
    if not blob:
        return None, None
    for pattern in (_LENGTH_OF_PHRASE, _LENGTH_WITH_UNIT):
        match = pattern.search(blob)
        if match:
            size = match.group(1)
            if "." in size and size.endswith("0"):
                size = size.rstrip("0").rstrip(".")
            return size, "m"
    return None, None


def parse_box_capacity_from_text(text: Any) -> str | None:
    """Return ``30X24X10`` style capacity from cabinet dimension prose."""
    match = _BOX_DIMENSIONS.search(str(text or ""))
    if not match:
        return None
    parts = [match.group(1), match.group(2), match.group(3)]
    normalized = [part.rstrip("0").rstrip(".") if "." in part else part for part in parts]
    return "X".join(normalized)


def parse_size_for_product(
    text: Any,
    *,
    category: Any = None,
    sub_category: Any = None,
    pattern: dict[str, Any] | None = None,
    require_explicit_unit: bool = True,
) -> tuple[str | None, str | None]:
    """
    Parse Size + Unit from BOQ text using catalog pattern for the product family.

    FIRE HOSE → length (m); PIPE/VALVE/branch pipe → mm dia; etc.
    """
    from utils.nominal_size import parse_nominal_size_from_text

    blob = str(text or "").strip()
    if not blob:
        return None, None

    cat, sub = _normalize_key(category, sub_category)
    units = expected_units(pattern)
    unit_hint = (pattern or {}).get("units") or []
    primary_unit = str(unit_hint[0]).lower() if unit_hint else ""

    if sub == "FIRE HOSE" or primary_unit == "m":
        length, length_unit = parse_length_from_text(blob)
        if length:
            return length, length_unit

    if sub in {"FIRE HOSE BOX", "FIRE DOOR"} or primary_unit == "inch":
        # Cabinets / doors: outer dimensions belong in Capacity, not Size.
        return None, None

    if primary_unit in {"kg", "liter", "kl", "lpm"}:
        # Weight/volume/flow products — do not parse mm dia as Size.
        match = re.search(r"(?i)(?<![0-9])(\d+(?:\.\d+)?)\s*(kg|kilogram|liter|litre|kl|lpm)\b", blob)
        if match:
            size = match.group(1)
            unit_token = match.group(2).lower()
            if unit_token in {"kilogram"}:
                return size, "kg"
            if unit_token in {"liter", "litre"}:
                return size, "liter"
            if unit_token == "kl":
                return size, "kl"
            if unit_token == "lpm":
                return size, "lpm"
        return None, None

    size, unit = parse_nominal_size_from_text(
        blob,
        require_explicit_unit=require_explicit_unit,
    )
    if size and is_swg_gauge_number(size, blob):
        return None, None
    if size and unit:
        return size, unit
    if size and primary_unit in {"mm", "nb", "cm"}:
        return size, primary_unit if primary_unit != "nb" else "NB"
    return size, unit


def format_size_rules_for_ai(patterns: list[dict[str, Any]] | None = None) -> str:
    """Compact Size/Unit/Capacity guidance for extraction prompts."""
    patterns = patterns or load_size_unit_patterns()
    if not patterns:
        return (
            "Size/Unit must match Rate_Master_Output for each sub-category. "
            "Prefer null when the BOQ measure type does not match the catalog Unit."
        )

    lines = [
        "Size / Unit / Capacity — match Product_Helper catalog patterns:",
        "- Size + Unit are ONE measure (never qty UOM like Each/Nos).",
        "- Never use SWG sheet gauge (18 SWG), IS numbers, cabinet WxHxD, or qty",
        "  digits as Size.",
    ]
    for item in patterns:
        units = ", ".join(item.get("units") or []) or "—"
        sizes = ", ".join(item.get("sample_sizes") or []) or "—"
        caps = ", ".join(item.get("sample_capacities") or []) or "—"
        meaning = item.get("size_meaning") or ""
        lines.append(
            f"  • {item['category']} / {item['sub_category']}: Unit=[{units}]; "
            f"samples size=[{sizes}] capacity=[{caps}]. {meaning}"
        )
    lines.extend(
        [
            "- FIRE HOSE: ``63mm dia 15m`` → size=15 unit=m (63mm dia is coupling, not Size).",
            "- BRANCH PIPE / SHORT BRANCH PIPE: outlet/coupling mm (e.g. 20mm outlet → 20 mm).",
            "- FIRE HOSE BOX: product is the cabinet; capacity=outer dims; size often 0.",
            "- PUMP: flow (lpm) → Capacity; size often 0.",
            "- VALVE PN rating → Capacity; nominal bore → Size.",
        ]
    )
    return "\n".join(lines)


def resolve_main_product_from_evidence(text: str) -> tuple[str | None, str | None]:
    """
    Return the primary purchasable product from BOQ prose.

    ``fire hose box … to accommodate branch pipes`` → FIRE HOSE BOX, not branch pipe.
    """
    blob = str(text or "").strip().lower()
    if not blob:
        return None, None
    for phrase, category, sub_category in _MAIN_PRODUCT_PHRASES:
        if phrase not in blob:
            continue
        # Contents mentioned after "accommodate/hold" must not beat the enclosure.
        if phrase in {"branch pipe", "short branch pipe", "fire hose", "hose reel"}:
            box_pos = max(
                blob.find("fire hose box"),
                blob.find("hose box"),
                blob.find("hose cabinet"),
            )
            branch_pos = blob.find(phrase)
            if box_pos >= 0 and branch_pos > box_pos and _CONTENT_CONTEXT.search(blob):
                continue
        return category, sub_category
    return None, None


def normalize_main_product_identity(
    product: dict[str, Any],
    *,
    evidence_text: str = "",
) -> dict[str, Any]:
    """Snap Category/Sub/Class onto the main product; drop child-product fields."""
    from apps.boq.services.boq_row_fields import is_blank as _is_blank_value

    item = dict(product)
    blob = str(evidence_text or "").strip()
    category, sub_category = resolve_main_product_from_evidence(blob)
    if not category or not sub_category:
        return item

    current_sub = str(item.get("sub_category") or "").strip().upper()
    target_sub = str(sub_category).strip().upper()
    if current_sub != target_sub:
        item["category"] = category
        item["sub_category"] = sub_category

    if target_sub == "FIRE HOSE BOX":
        item["category"] = category
        item["sub_category"] = sub_category
        if _is_blank_value(item.get("size")) or is_swg_gauge_number(
            str(item.get("size")), blob
        ):
            item["size"] = None
            item["unit"] = None
        box_capacity = parse_box_capacity_from_text(blob)
        if box_capacity:
            item["capacity"] = box_capacity
        if _MS_SHEET.search(blob):
            item["class"] = "MS"
        attrs = dict(item.get("attributes") or {})
        for key in list(attrs.keys()):
            if str(key).strip().lower() in {"type", "is", "is_standard"}:
                attrs[key] = None
        item["attributes"] = attrs

    if target_sub in _NO_NOMINAL_SIZE_SUBS and not _is_blank_value(item.get("size")):
        if is_swg_gauge_number(str(item.get("size")), blob):
            item["size"] = None
            item["unit"] = None
    return item


def normalize_catalog_size_capacity(
    product: dict[str, Any],
    *,
    pattern: dict[str, Any] | None = None,
    evidence_text: str = "",
) -> dict[str, Any]:
    """
    Align Size/Capacity with Product_Helper semantics.

    FIRE HOSE length often lands in ``capacity`` — move it to ``size`` when Unit=m.
    """
    from apps.boq.services.boq_row_fields import is_blank as _is_blank_value

    item = dict(product)
    pattern = pattern or pattern_for_product(item)
    unit_text = str(item.get("unit") or "").strip().lower()
    cat, sub = _normalize_key(item.get("category"), item.get("sub_category"))
    units = expected_units(pattern) if pattern else set()
    length_product = sub == "FIRE HOSE" or unit_text == "m" or "m" in units

    if length_product and unit_text == "m":
        length, _ = parse_length_from_text(evidence_text)
        if not length:
            length, _ = parse_length_from_text(str(item.get("description_hint") or ""))
        cap_text = str(item.get("capacity") or "").strip()
        size_text = str(item.get("size") or "").strip()

        if _is_blank_value(item.get("size")) and cap_text and cap_text.replace(".", "", 1).isdigit():
            item["size"] = cap_text.rstrip("0").rstrip(".") if "." in cap_text else cap_text
            item["capacity"] = None
        elif length and (
            _is_blank_value(item.get("size"))
            or (size_text and size_text != length and is_swg_gauge_number(size_text, evidence_text) is False)
        ):
            if size_text and size_text != length:
                from utils.nominal_size import is_invalid_extracted_size

                if is_invalid_extracted_size(
                    size_text,
                    context_text=evidence_text,
                    attributes=item.get("attributes"),
                ) or float(size_text or 0) > float(length or 0) * 3:
                    item["size"] = length
                    item["capacity"] = None
            elif _is_blank_value(item.get("size")):
                item["size"] = length
                item["capacity"] = None

    if sub in {"FIRE HOSE BOX", "FIRE DOOR"}:
        box_capacity = parse_box_capacity_from_text(evidence_text)
        if box_capacity and _is_blank_value(item.get("capacity")):
            item["capacity"] = box_capacity
        if _is_blank_value(item.get("size")) or str(item.get("size") or "").strip() in {"0", "0.0"}:
            item["size"] = None

    return item


def validate_size_unit_for_pattern(
    product: dict[str, Any],
    *,
    evidence_text: str = "",
    pattern: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Clear Size/Unit when they conflict with the catalog pattern or evidence."""
    item = dict(product)
    size = item.get("size")
    unit = item.get("unit")
    if size in (None, "") and unit in (None, ""):
        return item

    blob = str(evidence_text or "")
    size_text = str(size or "").strip()
    if size_text and blob and is_swg_gauge_number(size_text, blob):
        item["size"] = None
        item["unit"] = None
        return item

    if not pattern:
        return item

    allowed = expected_units(pattern)
    unit_text = str(unit or "").strip().lower()
    if unit_text and allowed and unit_text not in allowed:
        # Wrong measure type (e.g. mm on FIRE HOSE which uses m).
        item["size"] = None
        item["unit"] = None
        return item

    cat, sub = _normalize_key(item.get("category"), item.get("sub_category"))
    if sub == "FIRE HOSE" and size_text and blob:
        length, length_unit = parse_length_from_text(blob)
        if length and length != size_text:
            item["size"] = None
            item["unit"] = None
        elif not length and unit_text == "mm":
            item["size"] = None
            item["unit"] = None
    return item
