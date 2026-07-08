"""Vector product matching backed by local Chroma.

Third-priority strategy (docs/DATABASE_ARCHITECTURE.md - Search Strategy): when
exact/alias matching fails, compare the query embedding against the local
Chroma product index. Requires AI to be enabled and embeddings to have been
generated; otherwise returns no match.
"""
from __future__ import annotations

from ai.embeddings import generator
from ai.embeddings.chroma_store import ChromaEmbeddingStore


def _database_version_id(rates_by_code: dict) -> int | None:
    for rates in rates_by_code.values():
        for rate in rates:
            return rate.database_version_id
    return None


def _rates_by_id(rates_by_code: dict) -> dict[int, object]:
    rows = {}
    for rates in rates_by_code.values():
        for rate in rates:
            rows[rate.pk] = rate
    return rows


def find_embedding(query: str, rates_by_code: dict) -> tuple[object | None, float]:
    """Return (RateMaster, similarity_percent) for the best vector match.

    similarity_percent is 0-100. Returns (None, 0.0) when there are no stored
    embeddings for the active version or AI is disabled.
    """
    database_version_id = _database_version_id(rates_by_code)
    if database_version_id is None:
        return None, 0.0

    # Raises AIServiceError when disabled; the caller decides whether to skip.
    query_vector = generator.generate_embedding(query)
    hits = ChromaEmbeddingStore().query(
        query_vector,
        database_version_id=database_version_id,
        top_k=5,
    )

    rates_by_id = _rates_by_id(rates_by_code)
    for hit in hits:
        rate = rates_by_id.get(hit.rate_master_id)
        if rate is None:
            continue
        return (
            rate,
            round(hit.similarity * 100, 2),
        )

    return None, 0.0
