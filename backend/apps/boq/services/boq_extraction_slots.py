"""Slot evidence binding and section attribute sharing for BOQ extraction."""
from __future__ import annotations

import logging
import re
from typing import Any

from ai.context import (
    resolve_category_label,
    resolve_sub_category_label,
    snap_product_taxonomy,
)
from apps.boq.services.boq_extraction_fields import (
    _apply_one_qty,
    _is_qty_uom,
    normalize_product_fields,
)
from apps.boq.services.boq_row_fields import is_blank as _is_blank_value
from utils.attribute_parser import coerce_attributes_dict
from apps.boq.services.extraction_attribute_fields import COMMON_ATTRIBUTE_LABELS
from apps.boq.services.product_attribute_enrichment_service import (
    humanize_attribute_key,
)
from utils.product_synonyms import (
    MAKE_LIST_DESCRIPTION_HINTS,
    MAKE_LIST_SUB_CATEGORY_HINTS,
)

logger = logging.getLogger("boq_ai")


# Prefer these attribute keys first in AI Description (then any other filled attrs).
_DESCRIPTION_ATTR_PRIORITY: tuple[str, ...] = (
    "is",
    "type",
    "material",
    "body_material",
    "connection_type",
    "outlet_type",
    "mounting",
    "pressure_rating",
    "fire_rating",
    "seat_type",
    "end_connection",
    "spindle_type",
    "rating",
)

_SIZE_FROM_TEXT = re.compile(
    r"(?i)(?:^|[^0-9])(\d+(?:\.\d+)?)\s*(mm|nb|inch|in|cm)?\b"
)


_PN_RATING_FROM_TEXT = re.compile(r"(?i)\bPN\s*[- ]?\s*(\d+)\b")


_SHARED_SECTION_ATTR_KEYS = frozenset(
    {
        "is",
        "seat_type",
        "connection_type",
        "material",
        "body_material",
        "spindle_type",
        "rating",
        "pressure_rating",
        "end_connection",
    }
)


_SPEC_KEYWORDS = frozenset(
    {
        "speed",
        "capacity",
        "head",
        "pressure",
        "flow",
        "power",
        "voltage",
        "rpm",
        "efficiency",
        "dimension",
        "size",
        "weight",
        "model",
        "type",
    }
)


_SPEC_LABEL_ONLY = re.compile(
    r"^(?P<label>speed|capacity|head|pressure|flow|power|voltage|rpm|efficiency|"
    r"dimension|size|weight|model|type)"
    r"(?:\s*\([^)]*\))?"
    r"(?:\s*:.*)?$",
    re.IGNORECASE,
)


_SIZE_ONLY_HINT = re.compile(
    r"(?i)^\s*(?:[a-z]\)?\s*)?\d+(?:\.\d+)?\s*(?:mm|nb|inch|in|cm)?\s*(?:dia(?:meter)?)?\s*$"
)


def _is_spec_only_product(product: dict[str, Any]) -> bool:
    """Drop spec-label rows the model may still return as products."""
    if product.get("slot_fallback"):
        return False
    hint = str(product.get("description_hint") or "").strip()
    if not hint:
        return False
    if _SPEC_LABEL_ONLY.fullmatch(hint):
        return True
    if ":" in hint:
        label = hint.split(":", 1)[0].strip().lower()
        if label in _SPEC_KEYWORDS:
            return True
    return False


def _product_slot_identity(product: dict[str, Any]) -> tuple[str, str, str, str]:
    """Same BOQ product on the same slot — used to drop duplicate extracts."""
    hint = re.sub(
        r"\s+",
        " ",
        str(product.get("description_hint") or "").strip().lower(),
    )
    return (
        hint,
        str(product.get("category") or "").strip().lower(),
        str(product.get("sub_category") or "").strip().lower(),
        str(product.get("size") or "").strip().lower(),
    )


def _qty_rank(product: dict[str, Any]) -> float:
    """Prefer the copy that kept the BOQ slot quantity."""
    raw = product.get("quantity")
    if raw in (None, ""):
        return -1.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        text = str(raw).strip().lower()
        if text in {"rate only", "ro"}:
            return 0.0
        return -1.0


def _collapse_duplicate_slot_products(
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one product when AI emitted the same item twice on one Unit/Qty slot."""
    if len(products) <= 1:
        return products
    kept: list[dict[str, Any]] = []
    seen: dict[tuple[str, tuple[str, str, str, str]], int] = {}
    for product in products:
        item = dict(product)
        slot_id = str(item.get("qty_row_id") or item.get("source_row_id") or "")
        identity = _product_slot_identity(item)
        if not identity[0]:
            kept.append(item)
            continue
        key = (slot_id, identity)
        prior_index = seen.get(key)
        if prior_index is None:
            seen[key] = len(kept)
            kept.append(item)
            continue
        if _qty_rank(item) > _qty_rank(kept[prior_index]):
            kept[prior_index] = item
    for index, item in enumerate(kept):
        item["product_index"] = index
    return kept


def _filter_spec_products(
    products: list[dict[str, Any]],
    *,
    taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    filtered = [product for product in products if not _is_spec_only_product(product)]
    cleaned: list[dict[str, Any]] = []
    for index, product in enumerate(filtered):
        product = dict(product)
        product["product_index"] = index
        attrs = coerce_attributes_dict(product.get("attributes"))
        product["attributes"] = attrs
        for key in ("category", "sub_category", "class", "size", "unit", "capacity", "make_hint"):
            if key in product and product.get(key) is not None and str(product.get(key)).strip() == "":
                product[key] = None
        product = snap_product_taxonomy(product, taxonomy)
        cleaned.append(normalize_product_fields(product, preserve_class=True))
    return cleaned


def _parse_size_from_text(text: Any) -> tuple[str | None, str | None]:
    """
    Return (size, measurement_unit) from BOQ letter/size text.

    Prefers the first clear nominal size (e.g. ``200`` from ``200mm dia``).
    """
    blob = str(text or "").strip()
    if not blob:
        return None, None
    match = _SIZE_FROM_TEXT.search(blob)
    if not match:
        return None, None
    size = match.group(1)
    try:
        number = float(size)
        if number.is_integer():
            size = str(int(number))
    except ValueError:
        pass
    unit_token = (match.group(2) or "").strip().lower()
    unit = None
    if unit_token in {"mm", "cm", "nb"}:
        unit = "NB" if unit_token == "nb" else unit_token
    elif unit_token in {"inch", "in"}:
        unit = "inch"
    elif re.search(r"(?i)\bmm\b", blob):
        unit = "mm"
    return size, unit


def _parse_pn_capacity(text: Any) -> str | None:
    match = _PN_RATING_FROM_TEXT.search(str(text or ""))
    if not match:
        return None
    return f"PN{match.group(1)}"


def _section_product_noun(section_text: str) -> str:
    """Pull a short product noun from parent BOQ text for weak size-only hints.

    Prefer the purchasable family (pipe / valve) over system chapter names
    like ``Sprinkler System`` / ``Yard Hydrant System``.
    """
    blob = str(section_text or "").strip()
    if not blob:
        return ""
    # Pipework / "65 mm dia pipe" before bare "sprinkler" (system title noise).
    priority_patterns = (
        r"(?i)\b(sluice\s+valve|butterfly\s+valve|ball\s+valve|gate\s+valve|"
        r"non[\s-]?return\s+valve|check\s+valve|y[\s-]?strainer|strainer|"
        r"landing\s+valve|hose\s+reel|fire\s+pump|jockey\s+pump|"
        r"pressure\s+switch|flow\s+switch|ms\s+pipe|gi\s+pipe|"
        r"upright\s+sprinkler|pendant\s+sprinkler|pendent\s+sprinkler|"
        r"side\s*wall\s+sprinkler)\b",
        r"(?i)\b(pipework|piping|\d+\s*mm\s*dia\s+pipes?|pipes?)\b",
        r"(?i)\b(sprinkler\s+head|sprinkler)\b",
        r"(?i)\b(hydrant)\b",
    )
    for pattern in priority_patterns:
        match = re.search(pattern, blob)
        if match:
            noun = re.sub(r"\s+", " ", match.group(1)).strip()
            # Normalize "150 mm dia pipe" → "pipe"
            if re.match(r"(?i)^\d+\s*mm\s*dia\s+pipes?$", noun):
                return "pipe"
            if noun.lower() in {"pipework", "piping", "pipes"}:
                return "pipe"
            return noun
    return ""


def _normalize_hint_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _is_raw_slot_paste(hint: str, slot_desc: str) -> bool:
    """True when AI copied the Unit/Qty row instead of writing an understanding."""
    hint_norm = _normalize_hint_text(hint)
    slot_norm = _normalize_hint_text(slot_desc)
    if not hint_norm or not slot_norm:
        return False
    if hint_norm == slot_norm:
        return True
    # Slot is size-only and hint is essentially that size line.
    if _SIZE_ONLY_HINT.match(slot_desc) and (
        hint_norm == slot_norm or _SIZE_ONLY_HINT.match(hint)
    ):
        return True
    return False


def _format_description_attributes(
    attributes: Any,
    *,
    limit: int = 4,
) -> str:
    """Short attribute phrases for AI Description (IS, Type, Material, …)."""
    attrs = coerce_attributes_dict(attributes)
    if not attrs:
        return ""
    ordered_keys: list[str] = []
    seen: set[str] = set()
    for key in _DESCRIPTION_ATTR_PRIORITY:
        if key in attrs and key not in seen:
            ordered_keys.append(key)
            seen.add(key)
    for key in sorted(attrs.keys(), key=lambda item: str(item).lower()):
        norm = str(key).strip().lower()
        if norm and norm not in seen:
            ordered_keys.append(norm)
            seen.add(norm)
    parts: list[str] = []
    for key in ordered_keys:
        raw = attrs.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        label = COMMON_ATTRIBUTE_LABELS.get(key) or humanize_attribute_key(key)
        # "IS Standard 903" reads better than "is standard 903" mid-sentence.
        label_text = "IS" if label.strip().lower() in {"is", "is standard"} else label.lower()
        parts.append(f"{label_text} {value}")
        if len(parts) >= limit:
            break
    return ", ".join(parts)


def _trim_number(value: str) -> str:
    """``1.00`` → ``1`` so sizes read naturally."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".")[0]
    if re.fullmatch(r"\d+\.\d*?[1-9]0+", text):
        return text.rstrip("0")
    return text


def _natural_size_phrase(size: Any, unit: Any) -> str:
    size_text = _trim_number(size)
    if not size_text:
        return ""
    unit_text = str(unit or "").strip()
    if not unit_text:
        return size_text
    if unit_text.lower() == "mm":
        return f"{size_text} mm dia"
    return f"{size_text} {unit_text}"


def _natural_capacity_phrase(capacity: Any) -> str:
    text = _trim_number(capacity)
    if not text or text in {"0", "0.0", "0.00"}:
        return ""
    if re.match(r"(?i)^pn\s*\d+$", text):
        return text.upper().replace(" ", "")
    return f"capacity {text}"


def compose_description_hint(product: dict[str, Any]) -> str:
    """Write AI Description as a search-ready identity line.

    Always names Sub-category (primary), Category, Class, Size, Unit, Capacity
    in plain English so Chroma/SQL can fetch the right family — e.g.
    ``class C MS pipe (PIPE), 65 mm dia``.
    """
    category = str(product.get("category") or "").strip()
    sub_category = str(product.get("sub_category") or "").strip()
    product_class = str(product.get("class") or "").strip()
    if product_class.lower() in {"0", "0.0", "-", "--", "n/a", "na", "none"}:
        product_class = ""

    # Sub_Category is nearest to the purchasable name; Category is the family.
    identity = (sub_category or category).strip()
    if not identity:
        return ""
    identity_l = identity.lower()
    cat_l = category.lower()

    if product_class:
        lead = f"class {product_class} {identity_l}"
    else:
        lead = identity_l
    # Avoid "ms for pipe" when sub already implies pipe; still tag Category.
    if category and cat_l not in lead and cat_l not in identity_l:
        if sub_category:
            lead = f"{lead} ({cat_l})"
        else:
            lead = f"{lead} ({cat_l})"

    details: list[str] = []
    size_phrase = _natural_size_phrase(product.get("size"), product.get("unit"))
    if size_phrase:
        details.append(size_phrase)
    capacity_phrase = _natural_capacity_phrase(product.get("capacity"))
    if capacity_phrase:
        details.append(capacity_phrase)
    attr_text = _format_description_attributes(product.get("attributes"))
    if attr_text:
        details.append(f"with {attr_text}")

    sentence = lead if not details else f"{lead}, {', '.join(details)}"
    return sentence[:400]


_CHAPTER_OR_SIZE_ONLY_HINT = re.compile(
    r"(?i)^\s*(?:[a-z]\)?\s*)?(?:\d+(?:\.\d+)?\s*(?:mm|nb)?\s*(?:dia(?:meter)?)?\s*)?"
    r"(?:sprinkler|hydrant|yard\s+hydrant|fire\s+fighting)?(?:\s+system)?\s*$"
)


def _hint_lacks_product_identity(
    hint: str,
    product: dict[str, Any],
) -> bool:
    """True when AI Description cannot drive DB search (size-only / chapter title)."""
    text = str(hint or "").strip()
    if not text:
        return True
    if _SIZE_ONLY_HINT.match(text):
        return True
    if _CHAPTER_OR_SIZE_ONLY_HINT.match(text):
        return True
    # "65mm dia SPRINKLER" / "200mm" — no sub/category noun from taxonomy.
    sub = str(product.get("sub_category") or "").strip().lower()
    cat = str(product.get("category") or "").strip().lower()
    lowered = text.lower()
    if sub and sub in lowered:
        return False
    if cat and cat in lowered and cat not in {"sprinkler", "hydrant"}:
        return False
    # Must contain a product-family token beyond size/system titles.
    family_tokens = (
        "pipe",
        "valve",
        "pump",
        "hose",
        "tank",
        "gauge",
        "nozzle",
        "extinguisher",
        "fitting",
        "branch",
        "strainer",
        "hydrant",
        "sprinkler",
        "panel",
        "joint",
    )
    # Bare system word + size is not enough when Category is PIPE.
    has_family = any(tok in lowered for tok in family_tokens)
    if not has_family:
        return True
    if cat == "pipe" and "pipe" not in lowered and "piping" not in lowered:
        # "65mm dia sprinkler" while Category is PIPE — wrong identity for search.
        return True
    if cat == "valve" and "valve" not in lowered:
        return True
    return False


_BOQ_SUPPLY_PREFIX = re.compile(
    r"(?i)^(providing\s+and\s+fixing|supply(?:ing)?(?:\s+and\s+"
    r"(?:fixing|installing|laying))?|fixing)\s+"
)
_BOQ_COMPLETE_TAIL = re.compile(
    r"(?i)\s*,?\s*complete\s+with\b.*?(?=\(|$)|"
    r"\s*,?\s*all\s+complete\b.*?(?=\(|$)|"
    r"\s*,?\s*of\s+approved\s+make\b.*?(?=\(|$)"
)
_IS_STANDARD_REF = re.compile(r"(?i)\(\s*as\s+per\s+(IS\s*:?\s*[\d]+)\s*\)")


def _trim_product_context(product_context: str) -> str:
    """Owning supply sentence → compact product understanding (no BOQ boilerplate)."""
    text = " ".join(str(product_context or "").split()).strip()
    if not text:
        return ""
    is_ref = ""
    match = _IS_STANDARD_REF.search(text)
    if match:
        is_ref = re.sub(r"\s+", "", match.group(1), flags=re.IGNORECASE)
        is_ref = re.sub(r"(?i)^IS", "IS:", is_ref)
        if not is_ref.upper().startswith("IS:"):
            is_ref = f"IS:{is_ref}"
    text = _BOQ_SUPPLY_PREFIX.sub("", text).strip(" ,;")
    text = _BOQ_COMPLETE_TAIL.sub("", text).strip(" ,;")
    text = _IS_STANDARD_REF.sub("", text).strip(" ,;")
    if is_ref and is_ref.lower() not in text.lower():
        text = f"{text}, as per {is_ref}" if text else f"as per {is_ref}"
    return text[:320]


def _understanding_from_context(
    product: dict[str, Any],
    *,
    product_context: str,
    slot_desc: str = "",
) -> str:
    """Long AI Description grounded in the owning supply sentence + this size."""
    core = _trim_product_context(product_context)
    if not core:
        return ""
    size_phrase = _natural_size_phrase(product.get("size"), product.get("unit"))
    if not size_phrase:
        size, unit = _parse_size_from_text(slot_desc)
        size_phrase = _natural_size_phrase(size, unit)
    line = core
    if size_phrase and size_phrase.lower() not in line.lower():
        size_num = str(product.get("size") or "").strip()
        if not size_num or size_num not in line:
            line = f"{line}, {size_phrase}"
    capacity_phrase = _natural_capacity_phrase(product.get("capacity"))
    if capacity_phrase and capacity_phrase.lower() not in line.lower():
        line = f"{line}, {capacity_phrase}"
    return line[:400]


def _enrich_description_hint(
    product: dict[str, Any],
    *,
    section_text: str,
    slot_desc: str,
    product_context: str = "",
) -> str:
    """AI Description = search identity for this slot (cat/sub/class/size/…).

    Prefer a composed line from mapped Category/Sub_Category/Class/Size/Unit/
    Capacity. Never leave size-only or chapter-title text (``65mm dia SPRINKLER``,
    ``200mm``) — that breaks DB recall.
    """
    hint = str(product.get("description_hint") or "").strip()
    composed = compose_description_hint(product)
    understanding = _understanding_from_context(
        product,
        product_context=product_context or section_text,
        slot_desc=slot_desc,
    )
    weak = (
        _hint_lacks_product_identity(hint, product)
        or _is_raw_slot_paste(hint, slot_desc)
    )

    # Owning-sentence understanding wins when taxonomy compose disagrees
    # (e.g. wrong PIPE fields vs sluice-valve context).
    if understanding and composed and not _significant_overlap(understanding, composed):
        if weak or not _significant_overlap(hint, composed):
            return understanding

    if composed:
        if weak:
            return composed
        sub = str(product.get("sub_category") or "").strip().lower()
        cat = str(product.get("category") or "").strip().lower()
        same_family = (
            _significant_overlap(hint, composed)
            or (sub and sub in hint.lower())
            or (cat and cat in hint.lower())
        )
        if same_family:
            if sub and sub not in hint.lower():
                return composed
            if len(hint) >= 50 and not _hint_lacks_product_identity(hint, product):
                return hint[:400]
            return composed
        return composed

    if understanding and weak:
        return understanding
    if not weak and hint:
        return hint[:400]
    if understanding:
        return understanding

    size_phrase = _natural_size_phrase(product.get("size"), product.get("unit"))
    noun = (
        str(product.get("sub_category") or "").strip()
        or _section_product_noun(product_context or section_text)
        or str(product.get("category") or "").strip()
    )
    if noun and size_phrase:
        return f"{noun.lower()}, {size_phrase}"[:400]
    if noun:
        return str(noun).strip()[:400]
    if size_phrase:
        return size_phrase[:400]
    return (hint or slot_desc or "")[:400]


def _significant_overlap(left: str, right: str) -> bool:
    """True when both strings share a product-type noun (len≥4)."""
    left_tokens = {
        tok
        for tok in re.findall(r"[a-z0-9]+", (left or "").lower())
        if len(tok) >= 4
    }
    right_tokens = {
        tok
        for tok in re.findall(r"[a-z0-9]+", (right or "").lower())
        if len(tok) >= 4
    }
    return bool(left_tokens & right_tokens)


def _family_key(product: dict[str, Any]) -> tuple[str, str]:
    return (
        str(product.get("category") or "").strip().upper(),
        str(product.get("sub_category") or "").strip().upper(),
    )


def _hint_category_sub_from_text(
    text: str,
    *,
    taxonomy: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Map owning-sentence / hint text onto Rate_Master category + sub.

    Prefer purchasable product phrases (pipework, GI pipe, sluice valve) over
    system/chapter titles (External Hydrant System, Sprinkler System).
    """
    blob = str(text or "").strip().lower()
    if not blob:
        return None, None

    # Product-supply phrases beat system titles when both appear in one section.
    _PRODUCT_FIRST_CAT: tuple[tuple[str, str], ...] = (
        ("gi pipe", "PIPE"),
        ("g.i. pipe", "PIPE"),
        ("g.i pipe", "PIPE"),
        ("ms pipe", "PIPE"),
        ("m.s. pipe", "PIPE"),
        ("mild steel pipe", "PIPE"),
        ("galvanized iron pipe", "PIPE"),
        ("galvanised iron pipe", "PIPE"),
        ("dia pipe", "PIPE"),
        ("mm dia pipe", "PIPE"),
        ("pipework", "PIPE"),
        ("piping", "PIPE"),
        ("sluice valve", "VALVE"),
        ("butterfly valve", "VALVE"),
        ("ball valve", "VALVE"),
        ("check valve", "VALVE"),
        ("non return", "VALVE"),
        ("reflux", "VALVE"),
    )
    category_hint = None
    for phrase, cat in _PRODUCT_FIRST_CAT:
        if phrase in blob:
            category_hint = cat
            break
    if not category_hint:
        for phrase, cat in MAKE_LIST_DESCRIPTION_HINTS:
            if phrase in blob:
                category_hint = cat
                break

    _PRODUCT_FIRST_SUB: tuple[tuple[str, str], ...] = (
        ("gi pipe", "gi"),
        ("g.i. pipe", "gi"),
        ("g.i pipe", "gi"),
        ("ms pipe", "ms"),
        ("m.s. pipe", "ms"),
        ("mild steel pipe", "ms"),
        ("galvanized iron pipe", "gi"),
        ("galvanised iron pipe", "gi"),
        ("sluice valve", "sluice valve"),
        ("butterfly valve", "butterfly"),
        ("check valve", "non return valve"),
        ("non return", "non return valve"),
        ("reflux", "non return valve"),
    )
    sub_hint = None
    for phrase, sub in _PRODUCT_FIRST_SUB:
        if phrase in blob:
            sub_hint = sub
            break
    if not sub_hint:
        for phrase, sub in MAKE_LIST_SUB_CATEGORY_HINTS:
            # Skip hydrant system titles when the section is clearly pipework.
            if category_hint == "PIPE" and "hydrant" in phrase:
                continue
            if category_hint == "PIPE" and phrase in {
                "sprinkler",
                "upright sprinkler",
                "pendant sprinkler",
            }:
                continue
            if phrase in blob:
                sub_hint = sub
                break
    if not category_hint and not sub_hint:
        return None, None

    taxonomy = taxonomy or {}
    categories = list(taxonomy.get("categories") or [])
    by_category = dict(taxonomy.get("sub_categories_by_category") or {})
    category = None
    if category_hint:
        category = resolve_category_label(category_hint, categories) or (
            category_hint if not categories else None
        )
    sub_category = None
    if sub_hint:
        sub_category = resolve_sub_category_label(
            sub_hint,
            category=category,
            sub_categories_by_category=by_category,
        )
        # Never keep a free-text sub that is not a valid pair for this category.
        if not sub_category and not by_category:
            sub_category = sub_hint.upper()
    return category, sub_category


_CLASS_FROM_TEXT: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bheavy\s*class\b|\bclass\s*[\"']?c[\"']?\b"), "C"),
    (re.compile(r"(?i)\bmedium\s*class\b|\bclass\s*[\"']?b[\"']?\b"), "B"),
    (re.compile(r"(?i)\blight\s*class\b|\bclass\s*[\"']?a[\"']?\b"), "A"),
)
_PLACEHOLDER_CLASS_SNAP = frozenset(
    {"", "0", "0.0", "-", "--", "n/a", "na", "none", "null", "nil"}
)


def _snap_class_from_text(product: dict[str, Any], blob: str) -> dict[str, Any]:
    """Map free-text class phrases (Heavy Class → C) when Class is blank."""
    item = dict(product)
    current = str(item.get("class") or "").strip()
    if current.lower() not in _PLACEHOLDER_CLASS_SNAP:
        return item
    text = str(blob or "")
    if not text:
        return item
    for pattern, label in _CLASS_FROM_TEXT:
        if pattern.search(text):
            item["class"] = label
            break
    return item


def _snap_identity_from_product_context(
    product: dict[str, Any],
    *,
    product_context: str,
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Prefer category/sub/class from the owning supply sentence when AI drifted.

    Size-only slots under ``Providing and fixing Cast Iron sluice valve`` must
    stay VALVE / SLUICE VALVE even if the model returned PIPE from chapter noise.
    """
    item = dict(product)
    blob = " ".join(
        part
        for part in (
            str(product_context or "").strip(),
            str(item.get("description_hint") or "").strip(),
        )
        if part
    )
    category, sub_category = _hint_category_sub_from_text(blob, taxonomy=taxonomy)
    current_cat = str(item.get("category") or "").strip().upper()
    current_sub = str(item.get("sub_category") or "").strip().upper()
    target_cat = str(category or "").strip().upper()
    target_sub = str(sub_category or "").strip().upper()

    # Strong owning noun wins when AI category/sub disagree or are blank.
    if category and (not current_cat or (target_cat and current_cat != target_cat)):
        item["category"] = category
    if sub_category and (
        not current_sub or (target_sub and current_sub != target_sub)
    ):
        item["sub_category"] = sub_category
    item = _snap_class_from_text(item, blob)
    return snap_product_taxonomy(item, taxonomy)


def _slot_size_hint(slot: dict[str, Any]) -> str | None:
    """Prefer an explicit size_hint, else parse the slot's own description."""
    hint = slot.get("size_hint")
    if not _is_blank_value(hint):
        return str(hint).strip()
    size, _unit = _parse_size_from_text(
        slot.get("description") or slot.get("evidence_text") or ""
    )
    return size


def _apply_slot_evidence_fields(
    products: list[dict[str, Any]],
    *,
    group: dict[str, Any],
    slots: list[dict[str, Any]] | None = None,
    taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Bind per-slot size/unit/description from BOQ evidence and share parent specs.

    AI sometimes copies the first letter size onto later products, or fills only
    product 0 with shared PN / seat / IS attributes. This pass repairs those
    using the section's authoritative slots + owning ``product_context``.
    """
    if not products:
        return products

    rows = list(slots or group.get("slots") or group.get("qty_rows") or [])
    by_qty_row = {
        str(item.get("qty_row_id") or item.get("row_id") or ""): item
        for item in rows
        if item.get("qty_row_id") or item.get("row_id")
    }
    section_text = str(
        group.get("full_description")
        or group.get("description")
        or ""
    )

    filled: list[dict[str, Any]] = []
    for index, product in enumerate(products):
        item = dict(product)

        qty_row_id = str(item.get("qty_row_id") or item.get("source_row_id") or "").strip()
        slot = by_qty_row.get(qty_row_id) if qty_row_id else None
        if slot is None and index < len(rows):
            slot = rows[index]

        product_context = str((slot or {}).get("product_context") or "").strip()
        if slot:
            slot_desc = str(slot.get("description") or "").strip()
            evidence = str(
                slot.get("evidence_text") or product_context or slot_desc or section_text
            ).strip()
            size_hint = _slot_size_hint(slot)
            size_from_slot, unit_from_slot = _parse_size_from_text(
                slot_desc or evidence
            )
            if size_hint and not size_from_slot:
                size_from_slot = size_hint
            if size_from_slot:
                current_size = str(item.get("size") or "").strip()
                current_digits = re.sub(r"[^0-9.]", "", current_size)
                hint_digits = re.sub(r"[^0-9.]", "", str(size_from_slot))
                if _is_blank_value(item.get("size")) or (
                    hint_digits and current_digits and hint_digits != current_digits
                ):
                    item["size"] = size_from_slot
                if unit_from_slot and (
                    _is_blank_value(item.get("unit")) or _is_qty_uom(item.get("unit"))
                ):
                    item["unit"] = unit_from_slot

        # PN / capacity from owning sentence first (not whole chapter dump).
        context_pn = _parse_pn_capacity(product_context) or _parse_pn_capacity(
            str((slot or {}).get("evidence_text") or "")
        )
        if context_pn:
            current_cap = str(item.get("capacity") or "").strip()
            current_pn = _parse_pn_capacity(current_cap)
            if _is_blank_value(item.get("capacity")) or (
                current_pn and current_pn != context_pn
            ):
                item["capacity"] = context_pn

        item = _snap_identity_from_product_context(
            item,
            product_context=product_context,
            taxonomy=taxonomy,
        )
        filled.append(normalize_product_fields(item, preserve_class=True))

    filled = _share_section_attributes(filled)
    # Keep / repair AI Description after size/capacity/attrs + identity snap.
    finalized: list[dict[str, Any]] = []
    for index, product in enumerate(filled):
        item = dict(product)
        qty_row_id = str(item.get("qty_row_id") or item.get("source_row_id") or "").strip()
        slot = by_qty_row.get(qty_row_id) if qty_row_id else None
        if slot is None and index < len(rows):
            slot = rows[index]
        slot_desc = str((slot or {}).get("description") or "").strip()
        product_context = str((slot or {}).get("product_context") or "").strip()
        item["description_hint"] = _enrich_description_hint(
            item,
            section_text=section_text,
            slot_desc=slot_desc,
            product_context=product_context,
        )
        finalized.append(item)
    return finalized


def _share_section_attributes(
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copy shared parent attributes only within the same category/sub family."""
    if len(products) < 2:
        return products

    # Group by product family so pipe IS=1239 never lands on a sluice valve.
    by_family: dict[tuple[str, str], list[int]] = {}
    for index, product in enumerate(products):
        by_family.setdefault(_family_key(product), []).append(index)

    updated = [dict(product) for product in products]
    for indexes in by_family.values():
        if len(indexes) < 2:
            continue
        shared: dict[str, Any] = {}
        for index in indexes:
            attrs = coerce_attributes_dict(updated[index].get("attributes"))
            for key, value in attrs.items():
                key_norm = str(key).strip().lower()
                if key_norm not in _SHARED_SECTION_ATTR_KEYS:
                    continue
                if _is_blank_value(value):
                    continue
                if key_norm not in shared:
                    shared[key_norm] = value
        if not shared:
            continue
        for index in indexes:
            attrs = coerce_attributes_dict(updated[index].get("attributes"))
            changed = False
            for key, value in shared.items():
                existing_key = next(
                    (
                        candidate
                        for candidate in attrs
                        if str(candidate).strip().lower() == key
                    ),
                    key,
                )
                if _is_blank_value(attrs.get(existing_key)):
                    attrs[existing_key] = value
                    changed = True
            if changed:
                updated[index]["attributes"] = attrs
    return updated


def _group_slots(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the authoritative filled Unit/Qty slots for one section."""
    return list(group.get("slots") or group.get("qty_rows") or [])


def _slot_row_id(slot: dict[str, Any]) -> str:
    return str(slot.get("qty_row_id") or slot.get("row_id") or "").strip()


def _missing_product_slots(
    group: dict[str, Any],
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    """Find filled Unit/Qty slots not represented by any extracted product."""
    slots = _group_slots(group)
    if not slots:
        return []
    products = list(row.get("products") or [])
    covered_ids = {
        str(product.get("qty_row_id") or product.get("source_row_id") or "").strip()
        for product in products
        if str(product.get("qty_row_id") or product.get("source_row_id") or "").strip()
    }
    missing: list[dict[str, Any]] = []
    for index, slot in enumerate(slots):
        row_id = _slot_row_id(slot)
        if row_id:
            if row_id not in covered_ids:
                missing.append(slot)
            continue
        # Defensive fallback for malformed legacy slots without row ids.
        if index >= len(products):
            missing.append(slot)
    return missing


def _slot_fallback_product(
    group: dict[str, Any],
    slot: dict[str, Any],
    *,
    product_index: int,
) -> dict[str, Any]:
    """
    Preserve a filled BOQ slot if AI still omits it after the correction pass.

    This does not invent catalog facts. It keeps the slot's BOQ evidence visible
    for expert review and downstream matching instead of silently losing a line.
    """
    evidence = str(
        slot.get("evidence_text")
        or slot.get("product_context")
        or slot.get("description")
        or group.get("full_description")
        or "Product from BOQ Unit/Qty row"
    ).strip()
    row_id = _slot_row_id(slot)
    size_hint = _slot_size_hint(slot)
    size, size_unit = _parse_size_from_text(
        slot.get("description") or evidence
    )
    if size_hint and not size:
        size = size_hint
    product_context = str(slot.get("product_context") or "").strip()
    capacity = _parse_pn_capacity(product_context) or _parse_pn_capacity(
        group.get("full_description") or group.get("description") or evidence
    )
    # Prefer a short synthetic understanding over dumping the raw qty row.
    section_text = str(
        group.get("full_description") or group.get("description") or ""
    )
    noun = (
        _section_product_noun(product_context)
        or _section_product_noun(evidence)
        or _section_product_noun(section_text)
    )
    size_phrase = ""
    if size:
        unit_label = size_unit or "mm"
        size_phrase = f"{size}mm dia" if str(unit_label).lower() == "mm" else f"{size}{unit_label}"
    if noun and size_phrase:
        hint = f"{size_phrase} {noun}"
    elif noun:
        hint = noun
    elif size_phrase:
        hint = size_phrase
    else:
        hint = str(slot.get("description") or "").strip() or evidence
    product = {
        "product_index": product_index,
        "source_row_id": row_id,
        "qty_row_id": row_id,
        "slot_index": slot.get("slot_index", product_index),
        "slot_id": slot.get("slot_id"),
        "boq_serial": str(slot.get("serial") or "").strip() or None,
        "description_hint": hint[:500],
        "category": None,
        "sub_category": None,
        "class": None,
        "size": size,
        "unit": size_unit,
        "capacity": capacity,
        "make_hint": None,
        "attributes": {},
        "extraction_confidence": 0.0,
        "slot_fallback": True,
        "needs_extraction_review": True,
    }
    product = _snap_identity_from_product_context(
        product,
        product_context=product_context,
    )
    return _apply_one_qty(
        normalize_product_fields(product),
        qty=slot.get("qty"),
        unit=slot.get("unit"),
        qty_status=slot.get("qty_status"),
        boq_rate=slot.get("boq_rate"),
    )


def _ensure_minimum_slot_products(
    group: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    """Stabilize to one product per filled Unit/Qty slot (pad missing, trim extras)."""
    slots = list(_group_slots(group))
    updated = dict(row)
    products = list(updated.get("products") or [])

    if slots:
        by_slot: dict[str, list[dict[str, Any]]] = {
            str(slot.get("qty_row_id") or slot.get("row_id") or ""): []
            for slot in slots
            if slot.get("qty_row_id") or slot.get("row_id")
        }
        unbound: list[dict[str, Any]] = []
        for product in products:
            item = dict(product)
            slot_id = str(item.get("qty_row_id") or item.get("source_row_id") or "").strip()
            if slot_id and slot_id in by_slot:
                by_slot[slot_id].append(item)
            else:
                unbound.append(item)

        stabilized: list[dict[str, Any]] = []
        extras_trimmed = 0
        for slot in slots:
            slot_id = str(slot.get("qty_row_id") or slot.get("row_id") or "").strip()
            if not slot_id:
                continue
            candidates = list(by_slot.get(slot_id) or [])
            if not candidates and unbound:
                candidates = [unbound.pop(0)]
            if not candidates:
                stabilized.append(
                    _slot_fallback_product(
                        group,
                        slot,
                        product_index=len(stabilized),
                    )
                )
                continue
            # One product per slot — keep the strongest qty/evidence rank.
            candidates.sort(key=_qty_rank, reverse=True)
            chosen = dict(candidates[0])
            chosen["qty_row_id"] = slot_id
            chosen["source_row_id"] = slot_id
            chosen["slot_index"] = int(slot.get("slot_index") or len(stabilized))
            chosen["product_index"] = len(stabilized)
            stabilized.append(chosen)
            extras_trimmed += max(0, len(candidates) - 1)

        extras_trimmed += len(unbound)
        if extras_trimmed:
            logger.warning(
                "Trimmed %s extra AI product(s) for row=%s to match %s Unit/Qty slot(s)",
                extras_trimmed,
                group.get("row_id"),
                len(slots),
            )
            updated["slot_extra_products_trimmed"] = extras_trimmed

        products = stabilized
        missing_slots: list[dict[str, Any]] = []
    else:
        missing_slots = _missing_product_slots(group, {"products": products})
        for slot in missing_slots:
            products.append(
                _slot_fallback_product(
                    group,
                    slot,
                    product_index=len(products),
                )
            )

    for index, item in enumerate(products):
        item["product_index"] = index

    updated["products"] = _apply_slot_evidence_fields(
        products,
        group=group,
        slots=slots,
    )
    updated["skip_matching"] = False
    if missing_slots:
        updated["slot_shortfall_fallback_count"] = len(missing_slots)
    elif slots and any(p.get("slot_fallback") for p in updated["products"]):
        updated["slot_shortfall_fallback_count"] = sum(
            1 for p in updated["products"] if p.get("slot_fallback")
        )
    updated.pop("skip_reason", None)
    if missing_slots:
        logger.warning(
            "AI extraction still missed %s Unit/Qty slot(s) for row=%s; "
            "added BOQ-evidence review products",
            len(missing_slots),
            group.get("row_id"),
        )
    return updated
