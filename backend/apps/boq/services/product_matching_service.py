"""Structured + vector product matching against active Rate_Master_Output."""
from __future__ import annotations

import logging
import re
from typing import Any, cast

from django.db.models import Q

from ai.embeddings.chroma_store import ChromaEmbeddingStore, selection_amount
from ai.embeddings.generator import generate_embedding, generate_embeddings
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

# Size dominates when filled — wrong dia must not beat a correct size on soft cat/sub.
_TEXT_WEIGHTS = {
    "category": 22.0,
    "sub_category": 18.0,
    "class": 10.0,
    "size": 28.0,
    "unit": 5.0,
    "capacity": 10.0,
    "attributes": 14.0,
}
_CHROMA_WEIGHT = 0.25
_STRUCTURED_WEIGHT = 0.75
_SIZE_MISMATCH_PENALTY = 45.0
# Soft penalty when description nouns disagree with catalog labels (not a hard 29% floor).
_TYPE_MISMATCH_PENALTY = 35.0
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
            if len(raw) < 4 or raw in _TYPE_STOPWORDS:
                continue
            tokens.add(raw)
    return tokens


def product_type_conflicts(extracted: dict[str, Any], rate: Rate_Master_Output) -> bool:
    """True when BOQ wording names a different product family than the catalog row.

    Compares description nouns to Category + Sub_Category + Class (not Sub alone).
    Otherwise ``80mm pipe`` vs Sub_Category ``MS`` looked like a conflict and every
    correct PIPE match was hard-capped at 29%.
    """
    hint = extracted.get("description_hint")
    catalog_blob = " ".join(
        str(value or "") for value in (rate.Category, rate.Sub_Category, rate.Class)
    )
    extract_blob = " ".join(
        str(value or "")
        for value in (hint, extracted.get("sub_category"), extracted.get("category"))
    )
    left_text = _normalize_text(extract_blob)
    right_text = _normalize_text(catalog_blob)
    if left_text and right_text:
        for phrase_a, phrase_b in _CONFLICTING_PHRASE_PAIRS:
            if phrase_a in left_text and phrase_b in right_text:
                return True
            if phrase_b in left_text and phrase_a in right_text:
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

    # Filled extract taxonomy that already agrees with the row is not a conflict.
    if _text_match_score(extracted.get("category"), rate.Category) >= 0.75:
        return False
    if _text_match_score(extracted.get("sub_category"), rate.Sub_Category) >= 0.75:
        return False
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
    from utils.product_synonyms import MAKE_LIST_DESCRIPTION_HINTS

    direct = _hint_field_score(hint, category_label)
    if direct > 0:
        return direct
    hint_text = _normalize_text(hint)
    cat_text = _normalize_text(category_label)
    if not hint_text or not cat_text:
        return 0.0
    for phrase, mapped_category in MAKE_LIST_DESCRIPTION_HINTS:
        if phrase in hint_text and _normalize_text(mapped_category) == cat_text:
            return 0.85
    return 0.0


def _effective_size(extracted: dict[str, Any]) -> Any:
    """Prefer explicit size; else parse nominal size from the description hint."""
    if _is_filled(extracted.get("size")):
        return extracted.get("size")
    return _size_value(extracted.get("description_hint"))


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
) -> tuple[float, dict[str, Any]]:
    """Return 0-100 structured score using product fields only (never make/vendor).

    Core field weights stay in the denominator even when the extract leaves a
    field blank. Otherwise size+unit alone normalize to 100% for every same-size
    neighbor (including unrelated categories). Blank category/sub still get
    partial credit when ``description_hint`` clearly names the catalog label.
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

    effective_size = _size_for_score(_effective_size(extracted))
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

    for name, left, right, scorer in field_checks:
        weight = _TEXT_WEIGHTS[name]
        # Class/capacity/size: omit when neither side has a real value.
        if name in {"class", "capacity", "size"} and not _is_filled(left) and not _is_filled(right):
            continue
        # Catalog has no nominal size (Size=0 sentinel) — do not dilute or
        # penalize BOQ cabinet dims / letter sizes against a blank Size.
        if name == "size" and not _is_filled(right):
            continue
        weight_total += weight
        if not _is_filled(left):
            # Sparse extracts (slot fallback): let description vouch for cat/sub.
            if name == "category":
                hint_points = _hint_category_score(hint, right) * weight
                breakdown[name] = hint_points
                weighted_score += hint_points
            elif name == "sub_category":
                hint_points = _hint_field_score(hint, right) * weight
                breakdown[name] = hint_points
                weighted_score += hint_points
            else:
                breakdown[name] = 0.0
            continue
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

    if weight_total <= 0:
        return 0.0, breakdown

    total = (weighted_score / weight_total) * 100.0

    # Hard size gate: only when both sides have a real nominal size.
    if (
        _is_filled(effective_size)
        and _is_filled(rate_size)
        and not _sizes_compatible(effective_size, rate_size)
    ):
        total = max(0.0, total - _SIZE_MISMATCH_PENALTY)
        breakdown["size_mismatch_penalty"] = _SIZE_MISMATCH_PENALTY

    # Soft type penalty — keep related family matches usable (no rigid 29% floor).
    if product_type_conflicts(extracted, rate):
        total = max(0.0, total - _TYPE_MISMATCH_PENALTY)
        breakdown["description_type_mismatch"] = True

    return total, breakdown

def build_match_query_text(extracted: dict[str, Any]) -> str:
    """Build Chroma query text from filled product properties only (no make/vendor).

    Default: structured fields first so category/sub/size outweigh incidental nouns
    in a long description_hint.

    Re-analyse with an edited description_hint sets ``_hint_first_recall`` so the
    hint leads the query and stale taxonomy cannot dominate recall.
    """
    hint_first = bool(extracted.get("_hint_first_recall"))
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
        for key in ("size", "unit", "capacity", "class"):
            _append_field(key)
        # Stale category/sub from a wrong prior match stay last (or skipped when
        # the hint already names the product family).
        for key in ("category", "sub_category"):
            _append_field(key)
    else:
        for key in (
            "category",
            "sub_category",
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
    return " ".join(str(part).strip() for part in parts if _is_filled(part))


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
        except AIServiceError:
            logger.warning("Chroma query skipped; falling back to structured SQL filter")
            helper_hits = []
        except Exception:
            logger.exception("Chroma recall failed; falling back to structured SQL filter")
            helper_hits = []

        # Chroma returns Product_Helper Product_IDs — expand to Rate_Master rows.
        hits = self._rate_hits_from_helper_hits(helper_hits)
        # Always merge SQL neighbors so catalog rows are not missed when Chroma is weak.
        hits = self._merge_size_sql_hits(extracted, hits)

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
            pid = str(rate.Product_ID or "").strip()
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
        except AIServiceError:
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
            rate_size = _size_for_score(getattr(rate, "Size", None))
            extract_size = _size_for_score(extracted.get("size"))
            # Skip size gate when catalog Size is blank/sentinel (hose box Size=0).
            if (
                _is_filled(extract_size)
                and _is_filled(rate_size)
                and not _sizes_compatible(extract_size, rate_size)
            ):
                continue
            seen.add(rate.pk)
            merged.append(
                {
                    "rate_master_id": rate.pk,
                    "similarity": max(0.35, float(item.get("confidence") or 0) / 100.0),
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
        keep = max(int(result_limit or CANDIDATE_LIMIT), CANDIDATE_LIMIT)
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
                }
            )

        if not candidates:
            candidates = self._sql_fallback_candidates(extracted)

        # Prefer size-compatible candidates when extract size is known.
        # Keep catalog rows with blank/sentinel Size=0 (hose box) — they are not
        # nominal-dia products and must not be filtered out by cabinet dims.
        extract_size = _size_for_score(extracted.get("size"))
        if _is_filled(extract_size):
            sized = [
                item
                for item in candidates
                if (
                    not _is_filled(
                        _size_for_score(getattr(item.get("rate"), "Size", None))
                    )
                    or _sizes_compatible(
                        extract_size,
                        _size_for_score(getattr(item.get("rate"), "Size", None)),
                    )
                )
            ]
            if sized:
                candidates = sized

        candidates = _dedupe_candidates_by_product_id(candidates)

        if approved_makes:
            filtered = [
                candidate
                for candidate in candidates
                if MakeListConstraintService.make_is_allowed(candidate.get("make"), approved_makes)
            ]
            candidates = filtered

        if prefer_lowest_price and candidates:
            candidates.sort(
                key=lambda item: (
                    float(item.get("selection_amount") or 0.0),
                    -float(item.get("confidence") or 0.0),
                )
            )
        else:
            candidates.sort(key=lambda item: item["confidence"], reverse=True)

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
        Pass 2: category + size only (class/sub may use long vs short forms).
        Pass 3: size + material synonym text in Class/Sub/Attribute.
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
        # Pass 1 — tight filters (category uses synonym expansion).
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

        # Pass 2 — category + size only (catch DI vs ductile iron on Class).
        q2 = Q()
        if _is_filled(category):
            q2 = q_and(q2, _synonym_q(category, field="Category"))
        if size_filter:
            q2 = q_and(q2, size_filter)
        if q2 and q2 != q1:
            passes.append(base.filter(q2))

        # Pass 3 — size + synonym text anywhere on Class/Sub/Attribute/Category.
        material_blob = Q()
        for raw in (product_class, sub_category, category, extracted.get("description_hint")):
            if not _is_filled(raw) or _is_placeholder_class(raw):
                continue
            for term in expand_query_terms(raw):
                # Skip full-sentence dump terms — they never icontain-match labels.
                if len(str(term).strip()) > 48:
                    continue
                material_blob = q_or(material_blob, q(Class__icontains=term))
                material_blob = q_or(material_blob, q(Sub_Category__icontains=term))
                material_blob = q_or(material_blob, q(Category__icontains=term))
                material_blob = q_or(material_blob, q(Attribute__icontains=term))
        q3 = material_blob
        if size_filter:
            q3 = q_and(q3, size_filter) if q3 else size_filter
        if q3:
            passes.append(base.filter(q3))

        # Pass 4 — description/taxonomy text only (ignore size). Cabinet dimensions
        # like 30"x24"x10" must not hide FIRE HOSE BOX rows with blank Size.
        if material_blob:
            passes.append(base.filter(material_blob))

        seen: set[int] = set()
        candidates: list[dict[str, Any]] = []
        for queryset in passes:
            for rate in queryset[:60]:
                if rate.pk in seen:
                    continue
                seen.add(rate.pk)
                structured, breakdown = structured_match_score(extracted, rate)
                candidates.append(
                    {
                        "rate_master_id": rate.pk,
                        "product_id": rate.Product_ID,
                        "rate_id": rate.Rate_ID,
                        "tech_key": rate.display_key(),
                        "make": rate.Make,
                        "vendor": rate.Vendor,
                        "confidence": round(structured, 2),
                        "chroma_similarity": 0.0,
                        "structured_score": round(structured, 2),
                        "score_breakdown": breakdown,
                        "selection_amount": float(selection_amount(rate)),
                        "rate": rate,
                    }
                )
                if len(candidates) >= 80:
                    break
            if len(candidates) >= 80:
                break

        candidates.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
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
        keep = max(1, int(limit or 3))
        candidates = self._sql_fallback_candidates(extracted)
        candidates = _dedupe_candidates_by_product_id(candidates)
        candidates.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
        return candidates[:keep]


def rate_document_placeholder(extracted: dict[str, Any]) -> str:
    return build_match_query_text(extracted) or "product"
