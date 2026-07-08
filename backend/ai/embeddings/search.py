"""Chroma vector search resolved back to RateMaster rows."""
from __future__ import annotations

from ai.embeddings.chroma_store import ChromaEmbeddingStore
from apps.database_manager.models import RateMaster
from apps.matching.services.exact_match import selection_amount


def search(
    query_vector: list[float],
    database_version,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> list[tuple]:
    """Return top RateMaster rows from the local Chroma product index."""
    hits = ChromaEmbeddingStore().query(
        query_vector,
        database_version_id=database_version.pk,
        top_k=top_k,
    )
    rate_ids = [
        hit.rate_master_id
        for hit in hits
        if hit.similarity >= min_similarity and hit.rate_master_id
    ]
    if not rate_ids:
        return []

    rates_by_id: dict[int, RateMaster] = {}
    for rate in RateMaster.objects.filter(
        database_version=database_version,
        pk__in=rate_ids,
    ):
        existing = rates_by_id.get(rate.pk)
        if existing is None or selection_amount(rate) < selection_amount(existing):
            rates_by_id[rate.pk] = rate

    results = [
        (rates_by_id[hit.rate_master_id], hit.similarity)
        for hit in hits
        if hit.rate_master_id in rates_by_id and hit.similarity >= min_similarity
    ]
    results.sort(key=lambda item: item[1], reverse=True)
    return results[:top_k]
