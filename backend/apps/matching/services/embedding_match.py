"""Vector (embedding) product matching (Phase 5, Sprint 10).

Third-priority strategy (docs/DATABASE_ARCHITECTURE.md - Search Strategy): when
exact/alias matching fails, compare the query embedding against stored
ProductEmbedding vectors via cosine similarity. Requires AI to be enabled and
embeddings to have been generated; otherwise returns no match.

Stored vectors use JSON in V1 (migrates to pgvector later); cosine is computed
in Python here.
"""
from __future__ import annotations

import math

from ai.embeddings import generator
from apps.database_manager.models import ProductEmbedding
from apps.matching.services.exact_match import selection_amount
from utils.text import normalize


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_embedding(query: str, rates_by_code: dict) -> tuple[object | None, float]:
    """Return (RateMaster, similarity_percent) for the best vector match.

    similarity_percent is 0-100. Returns (None, 0.0) when there are no stored
    embeddings for the active version or AI is disabled.
    """
    embeddings = [
        emb
        for emb in ProductEmbedding.objects.all()
        if normalize(emb.product_code) in rates_by_code
    ]
    if not embeddings or not rates_by_code:
        return None, 0.0

    # Raises AIServiceError when disabled; the caller decides whether to skip.
    query_vector = generator.generate_embedding(query)

    best_code: str | None = None
    best_sim = 0.0
    for emb in embeddings:
        sim = _cosine(query_vector, emb.embedding_vector)
        if sim > best_sim:
            best_sim = sim
            best_code = normalize(emb.product_code)

    if best_code is None:
        return None, 0.0
    candidates = rates_by_code.get(best_code, [])
    return min(candidates, key=selection_amount, default=None), round(best_sim * 100, 2)
