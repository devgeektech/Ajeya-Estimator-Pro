"""Embedding / vector search over stored ProductEmbedding rows.

In V1 embeddings are stored as JSON arrays keyed by ``product_code``. A
pgvector migration is the first post-UAT backlog item
(docs/SESSION_STATE.md - Future Sprints).

ProductEmbedding schema (V1):
    product_code      CharField   — links back to RateMaster.product_code
    embedding_vector  JSONField   — list[float]
    generated_at      DateTimeField

No direct FK to RateMaster or DatabaseVersion exists in V1; the join is
performed via ``product_code`` scoped to the provided ``database_version``.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger("boq_ai")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [0, 1] between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search(
    query_vector: list[float],
    database_version,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> list[tuple]:
    """Return the top-k most similar RateMaster rows for ``query_vector``.

    Scores every ``ProductEmbedding`` row using cosine similarity, then resolves
    the winning ``product_code`` values back to ``RateMaster`` rows scoped to
    ``database_version`` (cheapest per product_code within the version).

    Args:
        query_vector:      The embedding to compare against (list[float]).
        database_version:  A ``DatabaseVersion`` instance to scope the results.
        top_k:             Maximum number of results to return.
        min_similarity:    Minimum cosine similarity threshold (0–1).

    Returns:
        A list of ``(RateMaster, float)`` tuples ordered by similarity desc.
        Returns an empty list when no ``ProductEmbedding`` rows exist.
    """
    from apps.database_manager.models import ProductEmbedding, RateMaster

    # Score every stored embedding.
    scored: list[tuple[str, float]] = []  # (product_code, similarity)
    for emb in ProductEmbedding.objects.only("product_code", "embedding_vector"):
        stored = emb.embedding_vector
        if not stored:
            continue
        try:
            sim = _cosine_similarity(query_vector, stored)
        except Exception:  # noqa: BLE001 — skip malformed embeddings
            logger.warning("search: skipping malformed embedding for %s", emb.product_code)
            continue
        if sim >= min_similarity:
            scored.append((emb.product_code, sim))

    if not scored:
        return []

    # Sort and take the top-k unique product codes.
    scored.sort(key=lambda t: t[1], reverse=True)
    top_codes_with_sim: dict[str, float] = {}
    for code, sim in scored:
        if code not in top_codes_with_sim:
            top_codes_with_sim[code] = sim
        if len(top_codes_with_sim) >= top_k:
            break

    # Resolve product_codes back to RateMaster rows within the given version.
    rate_masters = {
        rm.product_code: rm
        for rm in RateMaster.objects.filter(
            database_version=database_version,
            product_code__in=top_codes_with_sim.keys(),
        )
    }

    results = [
        (rate_masters[code], sim)
        for code, sim in top_codes_with_sim.items()
        if code in rate_masters
    ]
    # Re-sort after dict ordering (Python 3.7+ preserves insertion order, but
    # the rate_masters lookup may reorder, so be explicit).
    results.sort(key=lambda t: t[1], reverse=True)
    return results
