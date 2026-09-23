"""Structured + vector product matching against active Rate_Master_Output."""
from __future__ import annotations

import logging
import re
from typing import Any, cast

from django.db.models import Q

from ai.embeddings.chroma_store import ChromaEmbeddingStore, selection_amount
from ai.embeddings.generator import generate_embedding, generate_embeddings
from ai.errors import is_fatal_ai_limit_error
from apps.database_manager.models import Rate_Master_Output
from common.constants import MATCH_CONFIDENCE_THRESHOLD
from common.db import q, q_and, q_or
from common.exceptions import AIServiceError

from .make_list_constraint_service import MakeListConstraintService
from .boq_row_fields import is_filled as _is_filled, normalize_text as _normalize_text
from utils.attribute_parser import attribute_overlap_score, parse_attributes
from utils.product_synonyms import (
    expand_query_terms,
    labels_equivalent,
)

logger = logging.getLogger("boq_ai")

# Analysis UI + match result: top Rate_Master_Output neighbors.
CANDIDATE_LIMIT = 3
# Wider pool for AI validation on initial Analyse / rematch (UI still shows 3).
AI_CANDIDATE_LIMIT = 5

# Sub_Category is nearest to product identity; Category next; size still gates
# wrong dia but must not outrank a wrong family.
# sub_category is the strongest identity signal — raised to 35 (was 30).
# category reduced to 20 (was 24) since sub_category already implies it.
_TEXT_WEIGHTS = {
    "sub_category": 35.0,
    "category": 20.0,
    "class": 10.0,
    "size": 18.0,
    "unit": 5.0,
    "capacity": 8.0,
    "attributes": 12.0,
}
_CHROMA_WEIGHT = 0.25
_STRUCTURED_WEIGHT = 0.75
_SIZE_MISMATCH_PENALTY = 45.0
# Hard ceiling when description/family disagrees with the catalog row (below
# MATCH_CONFIDENCE_THRESHOLD so wrong family cannot auto-confirm).
_TYPE_MISMATCH_SCORE_CAP = 29.0
# Distinct product phrases that share family tokens (e.g. "hose") but must not match.
_CONFLICTING_PHRASE_PAIRS: tuple[tuple[str, str], ...] = (
    ("hose box", "hose reel"),
    ("hose cabinet", "hose reel"),
    ("fire hose box", "hose reel"),
    ("fire hose cabinet", "hose reel"),
    ("hose reel", "hose box"),
    ("hose reel", "hose cabinet"),
    ("hose reel", "fire hose box"),
    ("hose reel", "fire hose cabinet"),
    ("branch pipe", "hose box"),
    ("branch pipe", "fire hose box"),
    ("branch pipes", "fire hose box"),
    ("branch pipe", "hose cabinet"),
    ("short branch pipe", "fire hose box"),
    ("delivery hose", "fire hose box"),
    ("sluice valve", "pipe"),
    ("butterfly valve", "pipe"),
    ("ball valve", "pipe"),
    ("non return valve", "pipe"),
    ("check valve", "pipe"),
    ("sprinkler", "pipe"),
    ("hydrant", "gi pipe"),
    ("hydrant", "ms pipe"),
    ("hose box", "pipe"),
    ("hose reel", "pipe"),
    ("extinguisher", "pipe"),
)
# Exact Sub_Category pairs that must never cross-match (substring-safe).
_SUB_CATEGORY_CONFLICTS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"FIRE HOSE BOX", "FIRE HOSE"}),
        frozenset({"FIRE HOSE BOX", "FIRE DOOR"}),
        frozenset({"FIRE HOSE BOX", "BRANCH PIPE"}),
        frozenset({"FIRE HOSE BOX", "SHORT BRANCH PIPE"}),
        frozenset({"FIRE HOSE BOX", "FIRE HOSE REEL"}),
    }
)
# Valve subtypes share the token "valve" — must not match across subtypes.
_VALVE_SUBTYPE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("sluice", "sluice valve", "gate valve"),
    ("butterfly", "butterfly valve", "bfv", "bf valve"),
    ("ball", "ball valve"),
    (
        "non return",
        "non-return",
        "non return valve",
        "check valve",
        "nrv",
        "nr valve",
        "reflux",
        "reflux valve",
        "reflux type",
        "reflex",
        "reflex valve",
    ),
    ("air release", "air relief", "air valve", "arv"),
    ("y strainer", "y-strainer", "y type strainer"),
)
# Class ``0`` is a real Rate_Master token (valves). Only wipe non-class junk.
_PLACEHOLDER_CLASS = frozenset({"-", "--", "n/a", "na", "none", "null", "nil"})
_PN_CAPACITY = re.compile(r"(?i)\bPN\s*[- ]?\s*(\d+)\b")
# Words that do not identify a catalog product type.
_TYPE_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "into",
        "onto",
        "all",
        "any",
        "set",
        "sets",
        "item",
        "items",
        "type",
        "made",
        "out",
        "dia",
        "mm",
        "nb",
        "inch",
        "inches",
        "nos",
        "each",
        "complete",
        "required",
        "above",
        "below",
        "including",
        "approved",
        "heavy",
        "duty",
        "as",
        "per",
        "its",
        "etc",
        "size",
        "unit",
        "class",
    }
)


def _is_placeholder_class(value: Any) -> bool:
    if not _is_filled(value):
        return True
    return _normalize_text(value) in _PLACEHOLDER_CLASS


def _size_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"(\d+(?:\.\d+)?)", str(value))
        return float(match.group(1)) if match else None


def _sizes_compatible(left: Any, right: Any) -> bool:
    """True when either size is blank or nominal sizes match within 1."""
    left_size = _size_value(left)
    right_size = _size_value(right)
    if left_size is None or right_size is None:
        return True
    return abs(left_size - right_size) <= 1.0


def _text_match_score(left: Any, right: Any) -> float:
    left_text = _normalize_text(left)
    right_text = _normalize_text(right)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    # DI ↔ ductile iron, NRV ↔ non return valve, etc.
    if labels_equivalent(left, right):
        return 1.0
    if left_text in right_text or right_text in left_text:
        return 0.75
    return 0.0


def _size_match_score(left: Any, right: Any) -> float:
    left_size = _size_value(left)
    right_size = _size_value(right)
    if left_size is None or right_size is None:
        return 0.0
    if abs(left_size - right_size) <= 0.01:
        return 1.0
    if abs(left_size - right_size) <= 1.0:
        return 0.6
    return 0.0


def _significant_type_tokens(value: Any) -> set[str]:
    """Product-type nouns from a hint or catalog label, plus synonym expansions."""
    tokens: set[str] = set()
    texts = [str(value or "")]
    texts.extend(expand_query_terms(value))
    for text in texts:
        for raw in re.findall(r"[a-z0-9]+", _normalize_text(text)):
            if len(raw) < 3 or raw in _TYPE_STOPWORDS:
                continue
            tokens.add(raw)
    return tokens


def _valve_subtype(text: Any) -> str | None:
    """Canonical valve subtype from free text / catalog labels, or None."""
    norm = _normalize_text(text)
    if not norm:
        return None
    for group in _VALVE_SUBTYPE_GROUPS:
        for phrase in group:
            if phrase in norm:
                return group[0]
    return None


def product_type_conflicts(extracted: dict[str, Any], rate: Rate_Master_Output) -> bool:
    """True when BOQ wording names a different product family than the catalog row.

    Compares description nouns to Category + Sub_Category + Class (not Sub alone).
    ``description_hint`` / AI understanding wins: agreeing Category fields alone
    must not clear a conflict (PIPE extract + ``sluice valve`` hint vs PIPE row).
    Valve subtypes that share ``valve`` (butterfly vs sluice vs NRV) also conflict.
    """
    hint = extracted.get("description_hint")
    catalog_blob = " ".join(
        (value or "") for value in (rate.Category, rate.Sub_Category, rate.Class)
    )
    extract_blob = " ".join(
        str(value or "")
        for value in (hint, extracted.get("sub_category"), extracted.get("category"))
    )
    left_text = _normalize_text(extract_blob)
    right_text = _normalize_text(catalog_blob)
    extract_sub = str(extracted.get("sub_category") or "").strip().upper()
    catalog_sub = (rate.Sub_Category or "").strip().upper()
    if extract_sub and catalog_sub:
        pair = frozenset({extract_sub, catalog_sub})
        if pair in _SUB_CATEGORY_CONFLICTS:
            return True
    if left_text and right_text:
        for phrase_a, phrase_b in _CONFLICTING_PHRASE_PAIRS:
            if phrase_a in left_text and phrase_b in right_text:
                return True
            if phrase_b in left_text and phrase_a in right_text:
                return True

    left_valve = _valve_subtype(extract_blob)
    right_valve = _valve_subtype(catalog_blob)
    if left_valve and right_valve and left_valve != right_valve:
        return True

    hint_tokens = _significant_type_tokens(hint)
    if not hint_tokens:
        return False

    catalog_tokens: set[str] = set()
    for value in (rate.Category, rate.Sub_Category, rate.Class):
        catalog_tokens |= _significant_type_tokens(value)
    if not catalog_tokens:
        return False
    if hint_tokens & catalog_tokens:
        return False
    # Hint names a family absent from catalog labels (sluice/valve vs PIPE/GI).
    return True


def _hint_field_score(hint: Any, label: Any) -> float:
    """Partial credit when a core field is blank but the description names the label."""
    label_text = _normalize_text(label)
    hint_text = _normalize_text(hint)
    if not label_text or not hint_text:
        return 0.0
    if labels_equivalent(hint, label):
        return 0.9
    label_tokens = _significant_type_tokens(label)
    hint_tokens = _significant_type_tokens(hint)
    if label_tokens and label_tokens & hint_tokens:
        return 0.85
    if label_text in hint_text or hint_text in label_text:
        return 0.7
    return 0.0


def _hint_category_score(hint: Any, category_label: Any) -> float:
    """Credit Category from description phrases (e.g. sand buckets → HYDRANT)."""
    direct = _hint_field_score(hint, category_label)
    if direct > 0:
        return direct
    hint_text = _normalize_text(hint)
    cat_text = _normalize_text(category_label)
    if not hint_text or not cat_text:
        return 0.0

    from ai.context import load_rate_master_taxonomy
    from utils.product_synonyms import get_dynamic_taxonomy_hints
    
    taxonomy = load_rate_master_taxonomy()
    by_category = dict(taxonomy.get("sub_categories_by_category") or {})
    cat_hints, _ = get_dynamic_taxonomy_hints(by_category)
    
    for phrase, mapped_category in cat_hints:
        if phrase in hint_text and _normalize_text(mapped_category) == cat_text:
            return 0.85
    return 0.0


def _effective_size(extracted: dict[str, Any], taxonomy: dict[str, Any] | None = None) -> Any:
    """Prefer explicit size; else catalog length; else parse from description hint."""
    if _is_filled(extracted.get("size")):
        return extracted.get("size")
    sub = str(extracted.get("sub_category") or "").strip().upper()
    from utils.catalog_size_rules import parse_size_for_product

    no_size_subs = taxonomy.get("no_size_subs", frozenset()) if taxonomy else frozenset()
    if sub in no_size_subs:
        return None
    unit_text = str(extracted.get("unit") or "").strip().lower()
    if unit_text == "m" or sub == "FIRE HOSE":
        cap = extracted.get("capacity")
        if _is_filled(cap) and str(cap).replace(".", "", 1).isdigit():
            return cap
    hint = str(extracted.get("description_hint") or "")
    if re.search(r"(?i)\d+\s*[x×]\s*\d+\s*[x×]\s*\d+", hint):
        return None
    size, _unit = parse_size_for_product(
        hint,
        category=extracted.get("category"),
        sub_category=extracted.get("sub_category"),
        taxonomy=taxonomy,
    )
    if size:
        return size
    return None


def _capacity_match_score(left: Any, right: Any) -> float:
    """Soft-match PN ratings and exact capacity text; treat catalog ``0`` as blank."""
    left_text = _normalize_text(left)
    right_text = _normalize_text(right)
    if not left_text:
        return 0.0
    # Rate_Master pipes often store Capacity=0 as a sentinel — not a real match target.
    if right_text in {"", "0", "0.0"}:
        return 0.0
    left_pn = _PN_CAPACITY.search(str(left or ""))
    right_pn = _PN_CAPACITY.search(str(right or ""))
    if left_pn and right_pn:
        if left_pn.group(1) == right_pn.group(1):
            return 1.0
        return 0.15
    return _text_match_score(left, right)


def _class_for_score(value: Any) -> Any:
    """Ignore placeholder Class tokens (common valve Class=0 in Rate_Master)."""
    return None if _is_placeholder_class(value) else value


def _capacity_for_score(value: Any) -> Any:
    """Ignore blank / sentinel Capacity ``0`` so it does not dilute pipe matches."""
    if not _is_filled(value):
        return None
    if _normalize_text(value) in {"0", "0.0"}:
        return None
    return value


def _size_for_score(value: Any) -> Any:
    """Ignore blank / sentinel Size ``0`` / ``0.0`` (e.g. FIRE HOSE BOX).

    Catalog rows often store Size=0.00 when there is no nominal dia. Treating that
    as a real size caused −45 mismatch against cabinet dims (30x24x10) and stuck
    initial Analyse near ~40% while Re-analyse reached ~100%.
    """
    if not _is_filled(value):
        return None
    if _normalize_text(value) in {"0", "0.0"}:
        return None
    return value


def structured_match_score(
    extracted: dict[str, Any],
    rate: Rate_Master_Output,
    taxonomy: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    """Return 0-100 structured score using product fields only (never make/vendor).

    Only **filled extract fields** (and attributes the AI/expert found) count in
    the denominator — blank inputs are not treated as mismatches. Thin identity
    (only size/unit, no category/sub/hint) is capped so same-size unrelated
    neighbors cannot reach 100%.
    """
    extracted_attrs = {
        str(key): str(value)
        for key, value in (extracted.get("attributes") or {}).items()
        if _is_filled(value)
        and _normalize_text(key) not in {"make", "manufacturer", "brand", "supplier", "vendor"}
    }
    rate_attrs = {
        key: value
        for key, value in parse_attributes(rate.Attribute).items()
        if _normalize_text(key) not in {"make", "manufacturer", "brand", "supplier", "vendor"}
    }

    effective_size = _size_for_score(_effective_size(extracted, taxonomy=taxonomy))
    rate_size = _size_for_score(rate.Size)
    field_checks: list[tuple[str, Any, Any, Any]] = [
        ("category", extracted.get("category"), rate.Category, _text_match_score),
        ("sub_category", extracted.get("sub_category"), rate.Sub_Category, _text_match_score),
        (
            "class",
            _class_for_score(extracted.get("class")),
            _class_for_score(rate.Class),
            _text_match_score,
        ),
        ("size", effective_size, rate_size, _size_match_score),
        ("unit", extracted.get("unit"), rate.Unit, _text_match_score),
        (
            "capacity",
            _capacity_for_score(extracted.get("capacity")),
            _capacity_for_score(rate.Capacity),
            _capacity_match_score,
        ),
    ]

    breakdown: dict[str, Any] = {}
    weighted_score = 0.0
    weight_total = 0.0
    hint = extracted.get("description_hint")
    filled_core_names: set[str] = set()
    # Track fields that came from actual AI extractions (not hint-credit fallback).
    real_filled_names: set[str] = set()

    for name, left, right, scorer in field_checks:
        weight = _TEXT_WEIGHTS[name]
        # Class/capacity/size: omit when neither side has a real value.
        if name in {"class", "capacity", "size"} and not _is_filled(left) and not _is_filled(right):
            continue
        # Catalog has no nominal size (Size=0 sentinel) — do not dilute or
        # penalize BOQ cabinet dims / letter sizes against a blank Size.
        if name == "size" and not _is_filled(right):
            continue
        # Catalog Capacity=0 is a sentinel — do not score extract capacity against it.
        if name == "capacity" and not _is_filled(right):
            continue
        if not _is_filled(left):
            # Unfound extract field: do not count as a miss in general.
            # Exception: when there IS evidence of what the product is (description_hint
            # or category filled), a blank sub_category / category is a real gap
            # — count it as a scored miss so confidence reflects the missing identity.
            # If no evidence at all (genuinely unknown product), skip silently.
            has_evidence = _is_filled(hint) or _is_filled(extracted.get("category"))
            if name == "category":
                hint_ratio = _hint_category_score(hint, right)
                if hint_ratio > 0:
                    weight_total += weight
                    hint_points = hint_ratio * weight
                    breakdown[name] = hint_points
                    weighted_score += hint_points
                    filled_core_names.add(name)
                elif _is_filled(right) and has_evidence:
                    # Category is identifiable from evidence but was left blank — miss.
                    weight_total += weight
                    breakdown[name] = 0.0
                    breakdown["category_blank_miss"] = True
            elif name == "sub_category":
                hint_ratio = _hint_field_score(hint, right)
                if hint_ratio > 0:
                    weight_total += weight
                    hint_points = hint_ratio * weight
                    breakdown[name] = hint_points
                    weighted_score += hint_points
                    filled_core_names.add(name)
                elif _is_filled(right) and has_evidence:
                    # Sub_category identifiable from evidence but blank — scored miss.
                    # This prevents a 100% score when only size/category matched while
                    # sub_category (the strongest product identity) was missing.
                    weight_total += weight
                    breakdown[name] = 0.0
                    breakdown["sub_category_blank_miss"] = True
            else:
                breakdown[name] = None  # omitted — not found in BOQ/extract
            continue
        weight_total += weight
        filled_core_names.add(name)
        real_filled_names.add(name)  # actual AI/expert extraction — not hint credit
        points = scorer(left, right) * weight
        breakdown[name] = points
        weighted_score += points

    if extracted_attrs:
        attr_ratio, attr_scores = attribute_overlap_score(extracted_attrs, rate_attrs)
        weight = _TEXT_WEIGHTS["attributes"]
        breakdown["attributes"] = attr_ratio * weight
        breakdown["attribute_details"] = attr_scores
        weighted_score += attr_ratio * weight
        weight_total += weight
        real_filled_names.add("attributes")

    if weight_total <= 0:
        return 0.0, breakdown

    total = (weighted_score / weight_total) * 100.0

    # Hint-only guard: when no structured field was actually extracted by the AI
    # (only hint-credit from the raw BOQ description drove the score), the match
    # is speculative. Cap to a low value so these items never appear as high-
    # confidence matches — they should surface as uncertain / pending.
    _HINT_ONLY_SCORE_CAP = 25.0
    if not real_filled_names:
        total = min(total, _HINT_ONLY_SCORE_CAP)
        breakdown["hint_only_cap"] = _HINT_ONLY_SCORE_CAP

    # Thin identity: only size/unit (no family) must not look like a full match.
    identity_keys = {"category", "sub_category"}
    has_family = bool(identity_keys & filled_core_names) or bool(
        _significant_type_tokens(hint)
    )
    if not has_family and filled_core_names and filled_core_names <= {"size", "unit", "capacity"}:
        total = min(total, 55.0)
        breakdown["thin_identity_cap"] = 55.0

    # Hard size gate: only when both sides have a real nominal size.
    # Use a reduced penalty when sub_category taxonomy already matches — a
    # correct SLUICE VALVE at 200mm should outscore a PIPE/GI at exactly 250mm.
    if (
        _is_filled(effective_size)
        and _is_filled(rate_size)
        and not _sizes_compatible(effective_size, rate_size)
    ):
        extract_sub = _normalize_text(extracted.get("sub_category"))
        catalog_sub = _normalize_text(rate.Sub_Category)
        taxonomy_confirmed = bool(
            extract_sub and catalog_sub and labels_equivalent(extract_sub, catalog_sub)
        )
        penalty = 20.0 if taxonomy_confirmed else _SIZE_MISMATCH_PENALTY
        total = max(0.0, total - penalty)
        breakdown["size_mismatch_penalty"] = penalty

    # Hard family gate: wrong product type cannot clear the match threshold.
    if product_type_conflicts(extracted, rate):
        total = min(total, _TYPE_MISMATCH_SCORE_CAP)
        breakdown["description_type_mismatch"] = True

    return total, breakdown

def build_match_query_text(extracted: dict[str, Any]) -> str:
    """Build Chroma query text from filled product properties only (no make/vendor).

    Default: ``description_hint`` (AI Description) leads so search uses the
    understood product line. Structured fields follow for SQL/Chroma filters.

    Re-analyse with an edited description_hint also sets ``_hint_first_recall``.
    """
    hint_first = bool(extracted.get("_hint_first_recall")) or bool(
        str(extracted.get("description_hint") or "").strip()
    )
    hint = str(extracted.get("description_hint") or "").strip()
    parts: list[str] = []

    def _append_field(key: str) -> None:
        value = extracted.get(key)
        if not _is_filled(value):
            return
        text = str(value).strip()
        if text not in parts:
            parts.append(text)
        if key in {"class", "sub_category", "category", "description_hint"}:
            for term in expand_query_terms(value):
                if term not in parts:
                    parts.append(term)

    if hint_first and hint:
        _append_field("description_hint")
        for key in ("sub_category", "category", "class", "size", "unit", "capacity"):
            _append_field(key)
    else:
        for key in (
            "sub_category",
            "category",
            "class",
            "size",
            "unit",
            "capacity",
            "description_hint",
        ):
            _append_field(key)

    attrs = extracted.get("attributes") or {}
    for key, value in attrs.items():
        if not _is_filled(value):
            continue
        key_norm = _normalize_text(key)
        if key_norm in {"make", "manufacturer", "brand", "supplier", "vendor"}:
            continue
        parts.append(f"{key}={value}")
        if key_norm in {"material", "body_material", "construction", "moc", "type", "valve_type"}:
            for term in expand_query_terms(value):
                parts.append(f"{key}={term}")
    return " ".join(part.strip() for part in parts if _is_filled(part))


def _dedupe_candidates_by_product_id(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep the best-scoring row per Product_ID so make variants do not crowd top-N."""
    best_by_product: dict[str, dict[str, Any]] = {}
    leftovers: list[dict[str, Any]] = []
    for item in candidates:
        product_id = str(item.get("product_id") or "").strip()
        if not product_id:
            leftovers.append(item)
            continue
        prior = best_by_product.get(product_id)
        if prior is None or float(item.get("confidence") or 0) > float(
            prior.get("confidence") or 0
        ):
            best_by_product[product_id] = item
    merged = list(best_by_product.values()) + leftovers
    merged.sort(key=lambda row: float(row.get("confidence") or 0), reverse=True)
    return merged


class ProductMatchingService:
    """Match products via Product_Helper Chroma recall → Rate_Master_Output rows."""

    def __init__(self, database_version_id: int):
        self.database_version_id = database_version_id
        self._store = ChromaEmbeddingStore()

    def match_product(
        self,
        extracted: dict[str, Any],
        *,
        approved_makes: list[str] | None = None,
        prefer_lowest_price: bool = False,
        chroma_limit: int = 40,
        embedding: list[float] | None = None,
        result_limit: int | None = None,
    ) -> dict[str, Any]:
        query_text = build_match_query_text(extracted)
        try:
            vector = embedding
            if vector is None:
                vector = generate_embedding(query_text or rate_document_placeholder(extracted))
            helper_hits = self._store.query_similar(
                vector,
                limit=chroma_limit,
                database_version_id=self.database_version_id,
            )
        except AIServiceError as exc:
            if is_fatal_ai_limit_error(exc):
                raise
            logger.warning("Chroma query skipped; falling back to structured SQL filter")
            helper_hits = []
        except Exception:
            logger.exception("Chroma recall failed; falling back to structured SQL filter")
            helper_hits = []

        # Chroma returns Product_Helper Product_IDs — expand to Rate_Master rows.
        hits = self._rate_hits_from_helper_hits(helper_hits)
        # Always merge SQL neighbors so catalog rows are not missed when Chroma is weak.
        hits = self._merge_size_sql_hits(extracted, hits)
        # Guarantee that the extracted taxonomy (sub_category + category) is
        # represented in the candidate pool — Chroma alone can miss the correct
        # product family when the BOQ section text is pipe-heavy but the product
        # is a valve/hydrant item.
        hits = self._guarantee_taxonomy_hits(extracted, hits)

        return self._rank_candidates(
            extracted,
            hits=hits,
            approved_makes=approved_makes,
            prefer_lowest_price=prefer_lowest_price,
            result_limit=result_limit,
        )

    def _rate_hits_from_helper_hits(
        self,
        helper_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Map Product_Helper Chroma hits → one Rate_Master row per Product_ID.

        Analysis scores product identity (not Make/Vendor). Make & Vendor later
        loads all Rate_Master rows for the chosen Product_ID.
        """
        product_ids: list[str] = []
        similarity_by_pid: dict[str, float] = {}
        for hit in helper_hits:
            pid = str(hit.get("product_id") or "").strip()
            if not pid:
                continue
            sim = float(hit.get("similarity") or 0.0)
            if pid not in similarity_by_pid:
                product_ids.append(pid)
                similarity_by_pid[pid] = sim
            else:
                similarity_by_pid[pid] = max(similarity_by_pid[pid], sim)
        if not product_ids:
            return []

        rates = list(
            Rate_Master_Output.objects.filter(
                database_version_id=self.database_version_id,
                Product_ID__in=product_ids,
            ).order_by("pk")
        )
        # One representative rate per Product_ID (lowest Final_Material_Amount wins ties).
        best_by_pid: dict[str, Rate_Master_Output] = {}
        for rate in rates:
            pid = (rate.Product_ID or "").strip()
            if not pid:
                continue
            current = best_by_pid.get(pid)
            if current is None:
                best_by_pid[pid] = rate
                continue
            if selection_amount(rate) < selection_amount(current):
                best_by_pid[pid] = rate

        hits: list[dict[str, Any]] = []
        for pid in product_ids:
            rate = best_by_pid.get(pid)
            if rate is None:
                continue
            hits.append(
                {
                    "rate_master_id": rate.pk,
                    "product_id": pid,
                    "similarity": similarity_by_pid.get(pid, 0.0),
                }
            )
        return hits

    def match_products_batch(
        self,
        extracted_list: list[dict[str, Any]],
        *,
        chroma_limit: int = 40,
        result_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Match many products with one embedding API round-trip when possible."""
        if not extracted_list:
            return []
        texts = [
            build_match_query_text(item) or rate_document_placeholder(item)
            for item in extracted_list
        ]
        embeddings: list[list[float] | None]
        try:
            embeddings = cast(list[list[float] | None], generate_embeddings(texts))
        except AIServiceError as exc:
            if is_fatal_ai_limit_error(exc):
                raise
            logger.warning("Batch embedding failed; falling back to per-product recall")
            embeddings = [None] * len(extracted_list)

        return [
            self.match_product(
                extracted,
                chroma_limit=chroma_limit,
                embedding=vector,
                result_limit=result_limit,
            )
            for extracted, vector in zip(extracted_list, embeddings, strict=False)
        ]

    def _merge_size_sql_hits(
        self,
        extracted: dict[str, Any],
        hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Append SQL neighbors into the Chroma hit list (deduped by rate id)."""
        seen = {
            int(hit["rate_master_id"])
            for hit in hits
            if hit.get("rate_master_id") not in (None, "")
        }
        merged = list(hits)
        for item in self._sql_fallback_candidates(extracted)[:40]:
            rate = item.get("rate")
            if rate is None or rate.pk in seen:
                continue
            seen.add(rate.pk)
            merged.append(
                {
                    "rate_master_id": rate.pk,
                    "similarity": max(0.35, float(item.get("confidence") or 0) / 100.0),
                }
            )
        return merged

    def _guarantee_taxonomy_hits(
        self,
        extracted: dict[str, Any],
        hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Ensure catalog rows for the extracted taxonomy are in the candidate pool.

        When Chroma returns only wrong-family rows (e.g. PIPE hits when the BOQ
        section text is pipe-heavy but the product is a SLUICE VALVE), the correct
        sub_category rows never make it into the pool. This pass runs a direct
        sub_category + category SQL query and injects matching rows so `_rank_candidates`
        can score and surface them.
        """
        sub_category = extracted.get("sub_category")
        category = extracted.get("category")
        if not _is_filled(sub_category) or not _is_filled(category):
            return hits

        # Check if any existing hit already belongs to the correct taxonomy.
        existing_ids = {
            int(hit["rate_master_id"])
            for hit in hits
            if hit.get("rate_master_id") not in (None, "")
        }
        # Fast path: load rates for existing hits and see if any match taxonomy.
        from utils.product_synonyms import expand_query_terms
        rate_map = self._load_rates(list(existing_ids))
        sub_norm = _normalize_text(sub_category)
        cat_norm = _normalize_text(category)
        has_taxonomy_hit = any(
            _normalize_text(r.Sub_Category) == sub_norm
            and _normalize_text(r.Category) == cat_norm
            for r in rate_map.values()
        )
        if has_taxonomy_hit:
            return hits

        # No matching-taxonomy row in pool — run targeted SQL.
        from common.db import q as _q, q_and as _q_and, q_or as _q_or
        version_id = self.database_version_id
        base = Rate_Master_Output.objects.filter(database_version_id=version_id)

        def _syn_q(raw: Any, *, field: str) -> Q:
            query = Q()
            for term in expand_query_terms(raw):
                query = _q_or(query, _q(**{f"{field}__iexact": term}))
                query = _q_or(query, _q(**{f"{field}__icontains": term}))
            query = _q_or(query, _q(**{f"{field}__iexact": str(raw).strip()}))
            return query

        tax_q = _q_and(_syn_q(category, field="Category"), _syn_q(sub_category, field="Sub_Category"))
        merged = list(hits)
        for rate in base.filter(tax_q)[:20]:
            if rate.pk in existing_ids:
                continue
            existing_ids.add(rate.pk)
            merged.append(
                {
                    "rate_master_id": rate.pk,
                    "similarity": 0.40,  # Neutral similarity — structured score will rank it properly.
                }
            )
        return merged

    def _rank_candidates(
        self,
        extracted: dict[str, Any],
        *,
        hits: list[dict[str, Any]],
        approved_makes: list[str] | None = None,
        prefer_lowest_price: bool = False,
        result_limit: int | None = None,
    ) -> dict[str, Any]:
        keep = max(result_limit or CANDIDATE_LIMIT, CANDIDATE_LIMIT)
        candidates: list[dict[str, Any]] = []
        rate_map = self._load_rates([hit["rate_master_id"] for hit in hits])
        for hit in hits:
            rate = rate_map.get(hit["rate_master_id"])
            if rate is None:
                continue
            structured, breakdown = structured_match_score(extracted, rate)
            chroma_score = float(hit.get("similarity", 0.0)) * 100.0
            confidence = (_CHROMA_WEIGHT * chroma_score) + (_STRUCTURED_WEIGHT * structured)
            # Prefer catalog rows whose Sub_Category is named in the BOQ hint
            # (hose box → FIRE HOSE BOX) over near-family neighbors (hose reel).
            hint_boost = _hint_field_score(extracted.get("description_hint"), rate.Sub_Category)
            if hint_boost >= 0.85:
                confidence = min(100.0, confidence + 12.0)
            elif hint_boost >= 0.7:
                confidence = min(100.0, confidence + 6.0)
            # Wrong family/subtype cannot rise above the match floor via Chroma.
            type_mismatch = product_type_conflicts(extracted, rate)
            if type_mismatch:
                confidence = min(confidence, _TYPE_MISMATCH_SCORE_CAP)
            candidates.append(
                {
                    "rate_master_id": rate.pk,
                    "product_id": rate.Product_ID,
                    "rate_id": rate.Rate_ID,
                    "tech_key": rate.display_key(),
                    "make": rate.Make,
                    "vendor": rate.Vendor,
                    "confidence": round(confidence, 2),
                    "chroma_similarity": round(chroma_score, 2),
                    "structured_score": round(structured, 2),
                    "score_breakdown": breakdown,
                    "selection_amount": float(selection_amount(rate)),
                    "rate": rate,
                    "type_mismatch": type_mismatch,
                }
            )

        if not candidates:
            candidates = self._sql_fallback_candidates(extracted)

        candidates = _dedupe_candidates_by_product_id(candidates)

        if approved_makes:
            filtered = [
                candidate
                for candidate in candidates
                if MakeListConstraintService.make_is_allowed(candidate.get("make"), approved_makes)
            ]
            candidates = filtered

        extract_size = _size_for_score(extracted.get("size"))
        valid = [c for c in candidates if not c.get("type_mismatch")]
        conflicting = [c for c in candidates if c.get("type_mismatch")]

        extract_sub = _normalize_text(extracted.get("sub_category"))
        extract_cat = _normalize_text(extracted.get("category"))

        def _taxonomy_score(item: dict[str, Any]) -> float:
            """Score 0-2 for sub_category + category match — used as primary sort key.

            Ensures the correct product family (e.g. SLUICE VALVE) always ranks above
            a wrong-family row (e.g. PIPE/GI) that happens to share the nominal size,
            regardless of Chroma similarity.
            """
            rate = item.get("rate")
            if rate is None:
                return 0.0
            score = 0.0
            if extract_sub and labels_equivalent(extract_sub, _normalize_text(rate.Sub_Category)):
                score += 1.0
            if extract_cat and _normalize_text(rate.Category) == extract_cat:
                score += 0.5
            return score

        if valid:
            if prefer_lowest_price:
                valid.sort(
                    key=lambda item: (
                        float(item.get("selection_amount") or 0.0),
                        -float(item.get("confidence") or 0.0),
                    )
                )
                conflicting.sort(
                    key=lambda item: (
                        float(item.get("selection_amount") or 0.0),
                        -float(item.get("confidence") or 0.0),
                    )
                )
            else:
                # Primary sort: taxonomy match (sub_category first, then category).
                # Secondary sort: blended confidence descending.
                # This guarantees a correct SLUICE VALVE at nearby size outranks
                # a wrong PIPE row at the exact size.
                valid.sort(
                    key=lambda item: (
                        -_taxonomy_score(item),
                        -float(item.get("confidence") or 0.0),
                    )
                )
                conflicting.sort(key=lambda item: -float(item.get("confidence") or 0.0))
            candidates = valid + conflicting
        else:
            if prefer_lowest_price:
                candidates.sort(
                    key=lambda item: (
                        1 if item.get("type_mismatch") else 0,
                        float(item.get("selection_amount") or 0.0),
                        -float(item.get("confidence") or 0.0),
                    )
                )
            else:
                candidates.sort(
                    key=lambda item: (
                        1 if item.get("type_mismatch") else 0,
                        -float(item.get("confidence") or 0.0),
                    )
                )

        best = candidates[0] if candidates else None
        confidence = best["confidence"] if best else 0.0

        result: dict[str, Any] = {
            "status": "pending" if confidence < MATCH_CONFIDENCE_THRESHOLD else "matched",
            "confidence": confidence,
            "threshold": MATCH_CONFIDENCE_THRESHOLD,
            "approved_makes_applied": bool(approved_makes),
            "prefer_lowest_price": prefer_lowest_price,
            "candidates": [
                {
                    "rate_master_id": item["rate_master_id"],
                    "product_id": item["product_id"],
                    "rate_id": item["rate_id"],
                    "tech_key": item["tech_key"],
                    "make": item["make"],
                    "vendor": item["vendor"],
                    "confidence": item["confidence"],
                    "chroma_similarity": item["chroma_similarity"],
                    "structured_score": item["structured_score"],
                    "selection_amount": item.get("selection_amount"),
                }
                for item in candidates[:keep]
            ],
        }
        if best and confidence >= MATCH_CONFIDENCE_THRESHOLD:
            result["selected"] = {
                "rate_master_id": best["rate_master_id"],
                "product_id": best["product_id"],
                "rate_id": best["rate_id"],
                "tech_key": best["tech_key"],
                "make": best["make"],
                "vendor": best["vendor"],
                "selection_amount": best.get("selection_amount"),
            }
        return result

    def _load_rates(self, rate_ids: list[int]) -> dict[int, Rate_Master_Output]:
        if not rate_ids:
            return {}
        rows = Rate_Master_Output.objects.filter(
            pk__in=rate_ids,
            database_version_id=self.database_version_id,
        )
        return {row.pk: row for row in rows}

    def _sql_fallback_candidates(self, extracted: dict[str, Any]) -> list[dict[str, Any]]:
        """Recall Rate_Master rows by filled fields (synonym-aware, multi-pass).

        Pass 1: category + sub/class synonyms + size.
        Pass 2: category + sub synonyms + size.
        Pass 3: category + sub synonyms (same sub-category, any size in DB).
        Pass 4: category + size only (catch other subtypes of same category matching size).
        Pass 5: category only (same category, any size).
        Pass 6: size + material synonym text in Class/Sub/Attribute.
        Pass 7: description/taxonomy text only (ignore size).
        """
        version_id = self.database_version_id
        base = Rate_Master_Output.objects.filter(database_version_id=version_id)

        category = extracted.get("category")
        sub_category = extracted.get("sub_category")
        product_class = extracted.get("class")
        size = extracted.get("size")

        def _size_q() -> Q:
            if not _is_filled(size):
                return Q()
            size_token = str(size).strip()
            size_digits = re.sub(r"[^0-9.]", "", size_token)
            if size_digits:
                return q(Size__icontains=size_digits)
            return q(Size__icontains=size_token)

        def _synonym_q(raw: Any, *, field: str) -> Q:
            query = Q()
            if not _is_filled(raw):
                return query
            for term in expand_query_terms(raw):
                query = q_or(query, q(**{f"{field}__iexact": term}))
                query = q_or(query, q(**{f"{field}__icontains": term}))
            query = q_or(query, q(**{f"{field}__iexact": str(raw).strip()}))
            return query

        passes: list[Any] = []
        # Pass 1 — tight filters (category + sub + class + size).
        q1 = Q()
        if _is_filled(category):
            q1 = q_and(q1, _synonym_q(category, field="Category"))
        if _is_filled(sub_category):
            q1 = q_and(q1, _synonym_q(sub_category, field="Sub_Category"))
        if _is_filled(product_class) and not _is_placeholder_class(product_class):
            q1 = q_and(q1, _synonym_q(product_class, field="Class"))
        size_filter = _size_q()
        if size_filter:
            q1 = q_and(q1, size_filter)
        if q1:
            passes.append(base.filter(q1))

        # Pass 2 — category + sub_category + size
        q2 = Q()
        if _is_filled(category):
            q2 = q_and(q2, _synonym_q(category, field="Category"))
        if _is_filled(sub_category):
            q2 = q_and(q2, _synonym_q(sub_category, field="Sub_Category"))
        if size_filter:
            q2 = q_and(q2, size_filter)
        if q2 and q2 != q1:
            passes.append(base.filter(q2))

        # Pass 3 — category + sub_category (same product sub-category, any size in catalog)
        q3 = Q()
        if _is_filled(category):
            q3 = q_and(q3, _synonym_q(category, field="Category"))
        if _is_filled(sub_category):
            q3 = q_and(q3, _synonym_q(sub_category, field="Sub_Category"))
        if q3 and q3 != q2 and q3 != q1:
            passes.append(base.filter(q3))

        # Pass 4 — category + size only (catch DI vs ductile iron on Class).
        q4 = Q()
        if _is_filled(category):
            q4 = q_and(q4, _synonym_q(category, field="Category"))
        if size_filter:
            q4 = q_and(q4, size_filter)
        if q4 and q4 != q2 and q4 != q1:
            passes.append(base.filter(q4))

        # Pass 5 — category only (same category, any size).
        q5 = Q()
        if _is_filled(category):
            q5 = _synonym_q(category, field="Category")
        if q5 and q5 != q3:
            passes.append(base.filter(q5))

        # Pass 6 — size + synonym text anywhere on Class/Sub/Attribute/Category.
        material_blob = Q()
        for raw in (product_class, sub_category, category, extracted.get("description_hint")):
            if not _is_filled(raw) or _is_placeholder_class(raw):
                continue
            for term in expand_query_terms(raw):
                # Skip full-sentence dump terms — they never icontain-match labels.
                if len(term.strip()) > 48:
                    continue
                material_blob = q_or(material_blob, q(Class__icontains=term))
                material_blob = q_or(material_blob, q(Sub_Category__icontains=term))
                material_blob = q_or(material_blob, q(Category__icontains=term))
                material_blob = q_or(material_blob, q(Attribute__icontains=term))
        q6 = material_blob
        if size_filter:
            q6 = q_and(q6, size_filter) if q6 else size_filter
        if q6:
            passes.append(base.filter(q6))

        # Pass 7 — description/taxonomy text only (ignore size). Cabinet dimensions
        # like 30"x24"x10" must not hide FIRE HOSE BOX rows with blank Size.
        if material_blob and material_blob != q3:
            passes.append(base.filter(material_blob))

        seen: set[int] = set()
        candidates: list[dict[str, Any]] = []
        for queryset in passes:
            for rate in queryset[:60]:
                if rate.pk in seen:
                    continue
                seen.add(rate.pk)
                structured, breakdown = structured_match_score(extracted, rate)
                type_mismatch = product_type_conflicts(extracted, rate)
                confidence = structured
                if type_mismatch:
                    confidence = min(confidence, _TYPE_MISMATCH_SCORE_CAP)
                candidates.append(
                    {
                        "rate_master_id": rate.pk,
                        "product_id": rate.Product_ID,
                        "rate_id": rate.Rate_ID,
                        "tech_key": rate.display_key(),
                        "make": rate.Make,
                        "vendor": rate.Vendor,
                        "confidence": round(confidence, 2),
                        "chroma_similarity": 0.0,
                        "structured_score": round(structured, 2),
                        "score_breakdown": breakdown,
                        "selection_amount": float(selection_amount(rate)),
                        "rate": rate,
                        "type_mismatch": type_mismatch,
                    }
                )
                if len(candidates) >= 80:
                    break
            if len(candidates) >= 80:
                break

        extract_size = _size_for_score(extracted.get("size"))
        valid = [c for c in candidates if not c.get("type_mismatch")]
        conflicting = [c for c in candidates if c.get("type_mismatch")]
        if valid:
            if _is_filled(extract_size):
                valid_sized = [
                    c
                    for c in valid
                    if (
                        not _is_filled(
                            _size_for_score(getattr(c.get("rate"), "Size", None))
                        )
                        or _sizes_compatible(
                            extract_size,
                            _size_for_score(getattr(c.get("rate"), "Size", None)),
                        )
                    )
                ]
                if valid_sized:
                    valid_unsized = [c for c in valid if c not in valid_sized]
                    valid = valid_sized + valid_unsized
            valid.sort(key=lambda item: -float(item.get("confidence") or 0.0))
            conflicting.sort(key=lambda item: -float(item.get("confidence") or 0.0))
            candidates = valid + conflicting
        else:
            candidates.sort(
                key=lambda item: (
                    1 if item.get("type_mismatch") else 0,
                    -float(item.get("confidence") or 0.0),
                )
            )
        return candidates

    def recall_sql_candidates(
        self,
        extracted: dict[str, Any],
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Public SQL-only neighbor recall (no Chroma / embeddings / OpenAI).

        Used by Analysis display for unmatched products so tab GET stays read-only.
        """
        keep = max(1, limit or 3)
        candidates = self._sql_fallback_candidates(extracted)
        candidates = _dedupe_candidates_by_product_id(candidates)
        return candidates[:keep]


def rate_document_placeholder(extracted: dict[str, Any]) -> str:
    return build_match_query_text(extracted) or "product"
