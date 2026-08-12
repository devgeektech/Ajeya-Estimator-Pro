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
from common.exceptions import AIServiceError

from .make_list_constraint_service import MakeListConstraintService
from utils.attribute_parser import attribute_overlap_score, parse_attributes
from utils.product_synonyms import (
    expand_query_terms,
    labels_equivalent,
)

logger = logging.getLogger("boq_ai")

# Analysis UI + match result: top Rate_Master_Output neighbors.
CANDIDATE_LIMIT = 3

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


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


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
    """True when BOQ wording names a different product than the Rate_Master row.

    Stops ACCESSORIES / ROSETTEE PLATE confirming at high % against an
    electrical control panel just because category or overwritten fields match.
    """
    hint_tokens = _significant_type_tokens(extracted.get("description_hint"))
    if not hint_tokens:
        return False
    catalog_tokens = _significant_type_tokens(rate.Sub_Category)
    if not catalog_tokens:
        return False
    return hint_tokens.isdisjoint(catalog_tokens)


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


def structured_match_score(
    extracted: dict[str, Any],
    rate: Rate_Master_Output,
) -> tuple[float, dict[str, Any]]:
    """Return 0-100 structured score using product fields only (never make/vendor).

    Core field weights stay in the denominator even when the extract leaves a
    field blank. Otherwise size+unit alone normalize to 100% for every same-size
    neighbor (including unrelated categories).
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

    field_checks: list[tuple[str, Any, Any, Any]] = [
        ("category", extracted.get("category"), rate.Category, _text_match_score),
        ("sub_category", extracted.get("sub_category"), rate.Sub_Category, _text_match_score),
        (
            "class",
            _class_for_score(extracted.get("class")),
            _class_for_score(rate.Class),
            _text_match_score,
        ),
        ("size", extracted.get("size"), rate.Size, _size_match_score),
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

    for name, left, right, scorer in field_checks:
        weight = _TEXT_WEIGHTS[name]
        # Class/capacity: omit from the denom when neither side has a real value.
        if name in {"class", "capacity"} and not _is_filled(left) and not _is_filled(right):
            continue
        weight_total += weight
        if not _is_filled(left):
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

    # Hard size gate: wrong nominal size cannot win on soft category overlap.
    if _is_filled(extracted.get("size")) and not _sizes_compatible(
        extracted.get("size"), rate.Size
    ):
        total = max(0.0, total - _SIZE_MISMATCH_PENALTY)
        breakdown["size_mismatch_penalty"] = _SIZE_MISMATCH_PENALTY

    # BOQ description vs catalog sub-category: never auto-confirm a different product.
    if product_type_conflicts(extracted, rate):
        cap = max(0.0, float(MATCH_CONFIDENCE_THRESHOLD) - 1.0)
        if total > cap:
            total = cap
        breakdown["description_type_mismatch"] = True

    return total, breakdown


def build_match_query_text(extracted: dict[str, Any]) -> str:
    """Build Chroma query text from filled product properties only (no make/vendor)."""
    parts: list[str] = []
    for key in (
        "description_hint",
        "category",
        "sub_category",
        "class",
        "size",
        "unit",
        "capacity",
    ):
        value = extracted.get(key)
        if not _is_filled(value):
            continue
        parts.append(str(value).strip())
        # Expand DI ↔ ductile iron, NRV ↔ non return, etc. for vector recall.
        if key in {"class", "sub_category", "category", "description_hint"}:
            for term in expand_query_terms(value):
                if term not in parts:
                    parts.append(term)

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
    """Match products to Rate_Master_Output using vector recall and structured scoring."""

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
    ) -> dict[str, Any]:
        query_text = build_match_query_text(extracted)
        try:
            vector = embedding
            if vector is None:
                vector = generate_embedding(query_text or rate_document_placeholder(extracted))
            hits = self._store.query_similar(
                vector,
                limit=chroma_limit,
                database_version_id=self.database_version_id,
            )
        except AIServiceError:
            logger.warning("Chroma query skipped; falling back to structured SQL filter")
            hits = []
        except Exception:
            logger.exception("Chroma recall failed; falling back to structured SQL filter")
            hits = []

        # Always merge SQL neighbors so catalog rows are not missed when Chroma is weak.
        hits = self._merge_size_sql_hits(extracted, hits)

        return self._rank_candidates(
            extracted,
            hits=hits,
            approved_makes=approved_makes,
            prefer_lowest_price=prefer_lowest_price,
        )

    def match_products_batch(
        self,
        extracted_list: list[dict[str, Any]],
        *,
        chroma_limit: int = 40,
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
            if _is_filled(extracted.get("size")) and not _sizes_compatible(
                extracted.get("size"), rate.Size
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
    ) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        rate_map = self._load_rates([hit["rate_master_id"] for hit in hits])
        for hit in hits:
            rate = rate_map.get(hit["rate_master_id"])
            if rate is None:
                continue
            structured, breakdown = structured_match_score(extracted, rate)
            chroma_score = float(hit.get("similarity", 0.0)) * 100.0
            confidence = (_CHROMA_WEIGHT * chroma_score) + (_STRUCTURED_WEIGHT * structured)
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
        if _is_filled(extracted.get("size")):
            sized = [
                item
                for item in candidates
                if _sizes_compatible(
                    extracted.get("size"),
                    getattr(item.get("rate"), "Size", None),
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
                for item in candidates[:CANDIDATE_LIMIT]
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
                return Q(Size__icontains=size_digits)
            return Q(Size__icontains=size_token)

        def _synonym_q(raw: Any, *, field: str) -> Q:
            query = Q()
            if not _is_filled(raw):
                return query
            for term in expand_query_terms(raw):
                query |= Q(**{f"{field}__iexact": term})
                query |= Q(**{f"{field}__icontains": term})
            query |= Q(**{f"{field}__iexact": str(raw).strip()})
            return query

        passes: list[Any] = []
        # Pass 1 — tight filters.
        q1 = Q()
        if _is_filled(category):
            q1 &= Q(Category__iexact=str(category).strip())
        if _is_filled(sub_category):
            q1 &= _synonym_q(sub_category, field="Sub_Category")
        if _is_filled(product_class) and not _is_placeholder_class(product_class):
            q1 &= _synonym_q(product_class, field="Class")
        size_filter = _size_q()
        if size_filter:
            q1 &= size_filter
        if q1:
            passes.append(base.filter(q1))

        # Pass 2 — category + size only (catch DI vs ductile iron on Class).
        q2 = Q()
        if _is_filled(category):
            q2 &= Q(Category__iexact=str(category).strip())
        if size_filter:
            q2 &= size_filter
        if q2 and q2 != q1:
            passes.append(base.filter(q2))

        # Pass 3 — size + synonym text anywhere on Class/Sub/Attribute.
        material_blob = Q()
        for raw in (product_class, sub_category, extracted.get("description_hint")):
            if not _is_filled(raw) or _is_placeholder_class(raw):
                continue
            for term in expand_query_terms(raw):
                material_blob |= Q(Class__icontains=term)
                material_blob |= Q(Sub_Category__icontains=term)
                material_blob |= Q(Attribute__icontains=term)
        q3 = material_blob
        if size_filter:
            q3 = (q3 & size_filter) if q3 else size_filter
        if q3:
            passes.append(base.filter(q3))

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

def rate_document_placeholder(extracted: dict[str, Any]) -> str:
    return build_match_query_text(extracted) or "product"
