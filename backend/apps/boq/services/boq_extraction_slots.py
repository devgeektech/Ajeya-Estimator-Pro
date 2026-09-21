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
from apps.boq.services.boq_row_grouping_service import _is_size_only_slot_line
from utils.attribute_parser import coerce_attributes_dict
from utils.catalog_size_rules import load_size_unit_patterns, parse_size_for_product, pattern_for_product, snap_unit_to_pattern
from utils.nominal_size import (
    nominal_sizes_compatible,
    parse_nominal_size_from_text,
    sanitize_product_size,
)
from utils.product_extraction_sanitize import sanitize_product_against_evidence
from apps.boq.services.extraction_attribute_fields import COMMON_ATTRIBUTE_LABELS
from apps.boq.services.product_attribute_enrichment_service import (
    humanize_attribute_key,
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
        product = snap_product_taxonomy(product, taxonomy, infer_defaults=False)
        cleaned.append(normalize_product_fields(product, preserve_class=True))
    return cleaned


def _parse_size_from_text(
    text: Any,
    *,
    require_explicit_unit: bool = False,
) -> tuple[str | None, str | None]:
    """
    Return (size, measurement_unit) from BOQ letter/size text.

    Prefers nominal dia/mm sizes and ignores Indian Standard numbers (IS:636).
    """
    return parse_nominal_size_from_text(
        text,
        require_explicit_unit=require_explicit_unit,
    )


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
    blob = (section_text or "").strip()
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
    for key in sorted(attrs.keys(), key=lambda item: item.lower()):
        norm = str(key).strip().lower()
        if norm and norm not in seen:
            ordered_keys.append(norm)
            seen.add(norm)
    parts: list[str] = []
    for key in ordered_keys:
        raw = attrs.get(key)
        if raw is None:
            continue
        value = raw.strip()
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
    text = (value or "").strip()
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


def _hint_conflicts_with_taxonomy(hint: str, product: dict[str, Any]) -> bool:
    """True when AI Description names a different product family than mapped Sub."""
    from utils.catalog_size_rules import resolve_main_product_from_evidence

    sub = str(product.get("sub_category") or "").strip().upper()
    if not sub:
        return False
    text = (hint or "").strip()
    lowered = text.lower()
    if sub.replace("_", " ").lower() in lowered or sub.lower() in lowered:
        return False
    _, resolved_sub = resolve_main_product_from_evidence(text)
    if resolved_sub and resolved_sub.upper() != sub:
        return True
    if sub == "FIRE HOSE BOX" and "branch pipe" in lowered:
        return True
    if sub == "BRANCH PIPE" and any(
        token in lowered for token in ("fire hose box", "hose box", "hose cabinet")
    ):
        return True
    return False


def _hint_lacks_product_identity(
    hint: str,
    product: dict[str, Any],
) -> bool:
    """True when AI Description cannot drive DB search (size-only / chapter title)."""
    text = (hint or "").strip()
    if not text:
        return True
    if _hint_conflicts_with_taxonomy(text, product):
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
    text = " ".join((product_context or "").split()).strip()
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
        return noun.strip()[:400]
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
    blob = (text or "").strip().lower()
    if not blob:
        return None, None

    taxonomy = taxonomy or {}
    categories = list(taxonomy.get("categories") or [])
    by_category = dict(taxonomy.get("sub_categories_by_category") or {})
    
    category_hint = None
    sub_hint = None

    from utils.product_synonyms import get_dynamic_taxonomy_hints
    cat_hints, sub_hints = get_dynamic_taxonomy_hints(by_category)
    
    for phrase, cat in cat_hints:
        if phrase in blob:
            category_hint = cat
            break
            
    for phrase, sub in sub_hints:
        # Enclosure lines mention branch pipes / hoses as contents — not the buy.
        if phrase in {"branch pipe", "short branch pipe", "fire hose", "fire hose reel"}:
            if any(token in blob for token in ("fire hose box", "external fire hose box", "hose box", "hose cabinet")):
                continue
        # Skip hydrant system titles when the section is clearly pipework.
        if category_hint == "PIPE" and "hydrant" in phrase:
            continue
        if category_hint == "PIPE" and phrase in {"sprinkler", "upright sprinkler", "pendant sprinkler"}:
            continue
            
        if phrase in blob:
            sub_hint = sub
            break
            
    if not category_hint and not sub_hint:
        return None, None

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
    text = (blob or "")
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
    from utils.catalog_size_rules import (
        normalize_main_product_identity,
        resolve_main_product_from_evidence,
    )

    item = dict(product)
    blob = (product_context or "").strip()
    main_cat, main_sub = resolve_main_product_from_evidence(blob, taxonomy=taxonomy)
    if main_cat and main_sub:
        item = normalize_main_product_identity(item, evidence_text=blob, taxonomy=taxonomy)
        item = _snap_class_from_text(item, blob)
        return snap_product_taxonomy(item, taxonomy, infer_defaults=False)

    category, sub_category = _hint_category_sub_from_text(blob, taxonomy=taxonomy)
    current_cat = str(item.get("category") or "").strip().upper()
    current_sub = str(item.get("sub_category") or "").strip().upper()
    target_cat = (category or "").strip().upper()
    target_sub = (sub_category or "").strip().upper()

    # Strong owning noun wins when AI category/sub disagree or are blank.
    if category and (not current_cat or (target_cat and current_cat != target_cat)):
        item["category"] = category
    if sub_category and (
        not current_sub or (target_sub and current_sub != target_sub)
    ):
        item["sub_category"] = sub_category
    item = _snap_class_from_text(item, blob)
    return snap_product_taxonomy(item, taxonomy, infer_defaults=False)


def _slot_size_hint(slot: dict[str, Any]) -> str | None:
    """Prefer an explicit size_hint, else parse the slot's own description."""
    hint = slot.get("size_hint")
    if not _is_blank_value(hint):
        return str(hint).strip()
    size, _unit = _parse_size_from_text(
        slot.get("description") or slot.get("evidence_text") or ""
    )
    return size


def _slot_sizes_compatible(left: Any, right: Any) -> bool:
    """True when two nominal sizes are the same (within 1 mm)."""
    return nominal_sizes_compatible(left, right)


def build_product_boq_context(
    product: dict[str, Any],
    *,
    section_row: dict[str, Any] | None = None,
    boq_data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve section + per-slot BOQ text for one extracted product."""
    from apps.boq.services.boq_row_grouping_service import (
        full_description_for_row,
        single_row_description,
        slot_context_for_qty_row,
    )

    section_row = section_row or {}
    row_id = str(section_row.get("row_id") or "").strip()
    section_text = str(
        section_row.get("description")
        or section_row.get("full_description")
        or ""
    ).strip()
    if not section_text and boq_data and row_id:
        section_text = full_description_for_row(boq_data, row_id)

    slot_id = str(
        product.get("qty_row_id") or product.get("source_row_id") or ""
    ).strip()
    slot_meta = slot_context_for_qty_row(boq_data, slot_id) if boq_data else {
        "product_context": "",
        "evidence_text": "",
    }

    def _slot_line_only() -> str:
        """Unit/Qty letter line only — never sibling sizes from full lineage."""
        if not slot_id or not boq_data:
            return ""
        if slot_id == row_id:
            return str(product.get("description_hint") or "").strip()
        return single_row_description(boq_data, slot_id)

    existing = product.get("_boq_row")
    if isinstance(existing, dict):
        ctx = dict(existing)
        if not str(ctx.get("description") or "").strip() and section_text:
            ctx["description"] = section_text
        if not str(ctx.get("row_id") or "").strip() and row_id:
            ctx["row_id"] = row_id
        # Always prefer the single letter line when boq_data is available.
        repaired = _slot_line_only()
        if repaired:
            ctx["slot_description"] = repaired
        if not str(ctx.get("product_context") or "").strip():
            ctx["product_context"] = slot_meta.get("product_context") or ""
        if not str(ctx.get("evidence_text") or "").strip():
            ctx["evidence_text"] = slot_meta.get("evidence_text") or ""
        slot_desc = str(ctx.get("slot_description") or "").strip()
        return ctx if slot_desc or section_text else None

    slot_text = _slot_line_only()
    if not section_text and not slot_text:
        return None

    return {
        "row_id": row_id,
        "description": section_text,
        "slot_description": slot_text,
        "product_context": slot_meta.get("product_context") or "",
        "evidence_text": slot_meta.get("evidence_text") or "",
        "serial": str(section_row.get("serial") or section_row.get("ser_no") or ""),
    }


def _authoritative_slot_size(
    slot: dict[str, Any] | None,
    *,
    category: Any = None,
    sub_category: Any = None,
    pattern: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Size from the Unit/Qty row — overrides AI when letter sizes differ in one section.

    Operating-temp qty lines have no nominal size; fall back to product_context
    (e.g. parent ``Pendent sprinklers 15 mm``).
    """
    from utils.nominal_size import is_performance_spec_number, parse_operating_temp_from_text

    if not slot:
        return None, None
    slot_desc = str(slot.get("description") or "").strip()
    product_context = str(slot.get("product_context") or "").strip()
    evidence = str(slot.get("evidence_text") or "").strip()

    temp_only = bool(
        slot_desc
        and parse_operating_temp_from_text(slot_desc)
        and not re.search(r"(?i)\d+(?:\.\d+)?\s*(?:mm|nb|dia(?:meter)?)\b", slot_desc)
    )
    parse_texts = (
        [product_context, evidence]
        if temp_only
        else [slot_desc, product_context, evidence]
    )
    for parse_text in parse_texts:
        blob = (parse_text or "").strip()
        if not blob:
            continue
        size, unit = parse_size_for_product(
            blob,
            category=category,
            sub_category=sub_category,
            pattern=pattern,
            require_explicit_unit=True,
        )
        if size and not is_performance_spec_number(blob, size):
            return size, unit

    if not temp_only:
        size_hint = _slot_size_hint(slot)
        if size_hint and not is_performance_spec_number(
            slot_desc or product_context or evidence, size_hint
        ):
            return size_hint.strip(), None
    return None, None


def refresh_product_from_boq_context(
    product: dict[str, Any],
    *,
    boq_row: dict[str, Any] | None = None,
    taxonomy: dict[str, Any] | None = None,
    database_version_id: int | None = None,
    size_patterns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Re-apply BOQ evidence sanitization before rematch.

    Re-analyse uses stored Analysis fields; this pass re-reads the BOQ supply
    sentence so enclosure lines (fire hose box) are not rematched as contents
    (branch pipe / hose length inside the cabinet).
    """
    if not boq_row:
        return product

    from ai.context import load_rate_master_taxonomy

    section_text = str(
        boq_row.get("description") or boq_row.get("full_description") or ""
    ).strip()
    slot_desc = str(boq_row.get("slot_description") or "").strip()
    # Prefer the owning supply sentence when present (sprinkler parent for temp slots).
    product_context = str(boq_row.get("product_context") or "").strip()
    if not product_context:
        if slot_desc and _is_size_only_slot_line(slot_desc):
            product_context = section_text
        elif slot_desc:
            product_context = slot_desc
        else:
            product_context = section_text
    evidence_text = " ".join(
        part for part in (product_context, slot_desc, section_text) if part
    ).strip()

    tax = taxonomy
    if tax is None:
        tax = load_rate_master_taxonomy(database_version_id)

    if size_patterns is None and database_version_id is not None:
        size_patterns = load_size_unit_patterns(database_version_id)
    elif size_patterns is None:
        size_patterns = []

    work = dict(product)
    if slot_desc:
        pattern = pattern_for_product(work, size_patterns)
        auth_size, auth_unit = _authoritative_slot_size(
            {"description": slot_desc},
            category=work.get("category"),
            sub_category=work.get("sub_category"),
            pattern=pattern,
        )
        if auth_size:
            current_size = work.get("size")
            if _is_blank_value(current_size) or not _slot_sizes_compatible(
                current_size, auth_size
            ):
                work["size"] = auth_size
                if auth_unit:
                    work["unit"] = snap_unit_to_pattern(auth_unit, pattern) or auth_unit
                elif pattern:
                    snapped = snap_unit_to_pattern(work.get("unit"), pattern)
                    if snapped:
                        work["unit"] = snapped

    item = sanitize_product_against_evidence(
        work,
        product_context=product_context,
        slot_desc=slot_desc or product_context,
        evidence_text=evidence_text,
        section_text=section_text,
        taxonomy=tax,
        size_patterns=size_patterns,
    )
    item["description_hint"] = _enrich_description_hint(
        item,
        section_text=section_text,
        slot_desc=slot_desc,
        product_context=product_context or section_text,
    )
    return normalize_product_fields(item, preserve_class=True)


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
    size_patterns = load_size_unit_patterns()

    filled: list[dict[str, Any]] = []
    for index, product in enumerate(products):
        item = dict(product)

        qty_row_id = str(item.get("qty_row_id") or item.get("source_row_id") or "").strip()
        slot = by_qty_row.get(qty_row_id) if qty_row_id else None
        if slot is None and index < len(rows):
            slot = rows[index]

        product_context = str((slot or {}).get("product_context") or "").strip()
        slot_desc = str((slot or {}).get("description") or "").strip()
        evidence = str(
            (slot or {}).get("evidence_text") or product_context or slot_desc or section_text
        ).strip()

        # PN / capacity from owning sentence first (not whole chapter dump).
        context_pn = _parse_pn_capacity(product_context) or _parse_pn_capacity(
            str((slot or {}).get("evidence_text") or "")
        )
        if context_pn and _is_blank_value(item.get("capacity")):
            item["capacity"] = context_pn

        item = _snap_identity_from_product_context(
            item,
            product_context=product_context,
            taxonomy=taxonomy,
        )

        pattern = pattern_for_product(item, size_patterns)
        size_from_slot, unit_from_slot = _authoritative_slot_size(
            slot,
            category=item.get("category"),
            sub_category=item.get("sub_category"),
            pattern=pattern,
        )
        if size_from_slot:
            current_size = item.get("size")
            # AI often copies the first letter size (e.g. 80) onto later slots (150).
            if _is_blank_value(current_size) or not _slot_sizes_compatible(
                current_size, size_from_slot
            ):
                item["size"] = size_from_slot
                if unit_from_slot:
                    item["unit"] = snap_unit_to_pattern(unit_from_slot, pattern) or unit_from_slot
                elif pattern:
                    snapped = snap_unit_to_pattern(item.get("unit"), pattern)
                    if snapped:
                        item["unit"] = snapped

        item = sanitize_product_against_evidence(
            item,
            product_context=product_context,
            slot_desc=slot_desc,
            evidence_text=evidence,
            section_text=section_text,
            taxonomy=taxonomy,
            size_patterns=size_patterns,
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
        size_phrase = f"{size}mm dia" if unit_label.lower() == "mm" else f"{size}{unit_label}"
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
