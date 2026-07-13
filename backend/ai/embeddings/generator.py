"""OpenAI embedding generation and Chroma indexing for active master database."""
from __future__ import annotations

import logging
from typing import cast

from django.conf import settings

from ai.embeddings.chroma_store import ChromaEmbeddingStore, rate_document
from ai.instruction_log import log_instruction
from ai.openai_client import get_client, is_configured
from apps.database_manager.models import DatabaseVersion, Rate_Master
from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")

_OPENAI_MAX_EMBEDDING_INPUTS = 2048


def _embedding_batch_size() -> int:
    size = int(getattr(settings, "OPENAI_EMBEDDING_BATCH_SIZE", 500) or 500)
    return max(1, min(size, _OPENAI_MAX_EMBEDDING_INPUTS))


def generate_embedding(text: str) -> list[float]:
    """Return the embedding vector for ``text``.

    Raises AIServiceError when AI is disabled so callers can skip gracefully.
    """
    vectors = generate_embeddings([text])
    return vectors[0]


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Return embedding vectors for ``texts`` in a single OpenAI request."""
    if not texts:
        return []

    client = get_client()
    model = str(settings.OPENAI_EMBEDDING_MODEL)
    dimensions = int(getattr(settings, "OPENAI_EMBEDDING_DIMENSIONS", 1536) or 0)
    try:
        if dimensions:
            response = client.embeddings.create(
                model=model,
                input=texts,
                dimensions=dimensions,
            )
        else:
            response = client.embeddings.create(model=model, input=texts)
        ordered: list[list[float] | None] = [None] * len(texts)
        for item in response.data:
            ordered[item.index] = list(item.embedding)
        if any(vector is None for vector in ordered):
            raise AIServiceError("Embedding response missing one or more vectors.")
        instruction_text = "\n\n---\n\n".join(
            f"[{index + 1}] {text}" for index, text in enumerate(texts)
        )
        log_instruction(
            template_name="embedding",
            model=model,
            prompt=instruction_text,
            response=f"generated_vectors={len(texts)}",
            metadata={"batch_size": len(texts)},
        )
        return cast(list[list[float]], ordered)
    except AIServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise provider errors
        instruction_text = "\n\n---\n\n".join(
            f"[{index + 1}] {text}" for index, text in enumerate(texts)
        )
        log_instruction(
            template_name="embedding",
            model=model,
            prompt=instruction_text,
            error=str(exc),
            metadata={"batch_size": len(texts)},
        )
        logger.exception("Embedding generation failed")
        raise AIServiceError(f"Embedding request failed: {exc}") from exc


def _index_rate_batch(
    store: ChromaEmbeddingStore,
    rates: list[Rate_Master],
    texts: list[str],
) -> tuple[int, int]:
    """Index one batch of Rate_Master rows; return (generated, errors)."""
    if not rates:
        return 0, 0

    try:
        vectors = generate_embeddings(texts)
        store.upsert_rates(rates, vectors)
        return len(rates), 0
    except AIServiceError:
        logger.exception(
            "Embedding batch failed for %s Rate_Master rows; retrying row-by-row",
            len(rates),
        )

    generated = errors = 0
    for rate, text in zip(rates, texts, strict=True):
        try:
            vector = generate_embedding(text)
            store.upsert_rate(rate, vector)
            generated += 1
        except AIServiceError:
            logger.exception("Embedding failed for Rate_Master row %s", rate.pk)
            errors += 1
        except Exception:
            logger.exception("Chroma indexing failed for Rate_Master row %s", rate.pk)
            errors += 1
    return generated, errors


def generate_embeddings_for_version(database_version_id: int) -> dict:
    """Index Rate_Master rows for the active database version into Chroma.

    Each row is stored separately in Chroma with its own vector, document text,
    and metadata (including ``tech_key``). Batching is used only for OpenAI API
    calls and Chroma writes; storage remains row-wise.

    Clears the entire Chroma collection first so only the active database has
    embeddings at any time.
    """
    if not is_configured():
        logger.info(
            "Embedding generation skipped for version %s because AI is disabled.",
            database_version_id,
        )
        return {"total": 0, "generated": 0, "skipped": 0, "errors": 0}

    try:
        version = DatabaseVersion.objects.get(pk=database_version_id, is_active=True)
    except DatabaseVersion.DoesNotExist:
        logger.error(
            "Active DatabaseVersion %s not found for embedding generation",
            database_version_id,
        )
        return {"total": 0, "generated": 0, "skipped": 0, "errors": 1}

    products = (
        Rate_Master.objects.filter(database_version=version)
        .select_related("database_version")
        .iterator(chunk_size=_embedding_batch_size())
    )
    total = Rate_Master.objects.filter(database_version=version).count()
    generated = skipped = errors = 0
    store = ChromaEmbeddingStore()
    store.reset_all()

    pending_rates: list[Rate_Master] = []
    pending_texts: list[str] = []
    batch_size = _embedding_batch_size()

    for product in products:
        text = rate_document(product)
        if not text.strip():
            skipped += 1
            continue

        pending_rates.append(product)
        pending_texts.append(text)
        if len(pending_rates) < batch_size:
            continue

        batch_generated, batch_errors = _index_rate_batch(
            store, pending_rates, pending_texts
        )
        generated += batch_generated
        errors += batch_errors
        pending_rates = []
        pending_texts = []

    if pending_rates:
        batch_generated, batch_errors = _index_rate_batch(
            store, pending_rates, pending_texts
        )
        generated += batch_generated
        errors += batch_errors

    summary = {"total": total, "generated": generated, "skipped": skipped, "errors": errors}
    logger.info("Embedding generation summary for version %s: %s", database_version_id, summary)
    return summary
