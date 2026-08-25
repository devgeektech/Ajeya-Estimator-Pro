"""OpenAI embedding generation and Chroma indexing for Product_Helper."""
from __future__ import annotations

import logging
from typing import Any, cast

from django.conf import settings

from ai.embeddings.chroma_store import ChromaEmbeddingStore, helper_document
from ai.instruction_log import log_instruction
from ai.openai_client import get_client, is_configured
from apps.database_manager.models import DatabaseVersion, Product_Helper
from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")

_OPENAI_MAX_EMBEDDING_INPUTS = 2048
_DISCONTINUED_STATUS = frozenset(
    {
        "discontinued",
        "discontinue",
        "inactive",
        "obsolete",
        "withdrawn",
    }
)


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
            f"[{index + 1}] {text[:240]}{'…' if len(text) > 240 else ''}"
            for index, text in enumerate(texts[:20])
        )
        if len(texts) > 20:
            instruction_text += f"\n\n…and {len(texts) - 20} more inputs"
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
            f"[{index + 1}] {text[:240]}{'…' if len(text) > 240 else ''}"
            for index, text in enumerate(texts[:20])
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


def _is_discontinued(status: Any) -> bool:
    return str(status or "").strip().casefold() in _DISCONTINUED_STATUS


def _index_helper_batch(
    store: ChromaEmbeddingStore,
    helpers: list[Product_Helper],
    texts: list[str],
) -> tuple[int, int]:
    """Index one batch of Product_Helper rows; return (generated, errors)."""
    if not helpers:
        return 0, 0

    try:
        vectors = generate_embeddings(texts)
        store.upsert_helpers(helpers, vectors)
        return len(helpers), 0
    except AIServiceError:
        logger.exception(
            "Embedding batch failed for %s Product_Helper rows; retrying row-by-row",
            len(helpers),
        )

    generated = errors = 0
    for helper, text in zip(helpers, texts, strict=True):
        try:
            vector = generate_embedding(text)
            store.upsert_helper(helper, vector)
            generated += 1
        except AIServiceError:
            logger.exception("Embedding failed for Product_Helper row %s", helper.pk)
            errors += 1
        except Exception:
            logger.exception("Chroma indexing failed for Product_Helper row %s", helper.pk)
            errors += 1
    return generated, errors


def generate_embeddings_for_version(
    database_version_id: int,
    *,
    require_success: bool = False,
) -> dict:
    """Index Product_Helper rows for a database version into Chroma.

    One vector per Product_Helper row (complete catalog fields). Discontinued
    Status rows are never embedded. Rate_Master / Labour stay in Postgres and
    are joined by Product_ID after search.

    Does **not** clear other versions until the caller finishes a successful
    import (see ``replace_embeddings_with_version``). That avoids wiping the
    live index when a new import's embeddings fail.

    When ``require_success`` is True (database import path):

    - OpenAI must be configured when there are embeddable Product_Helper rows.
    - Any batch/row embedding error fails the whole operation.
    - Generated count must equal every non-skipped helper row.
    """
    helpers_qs = Product_Helper.objects.filter(
        database_version_id=database_version_id
    ).select_related("database_version")
    total = helpers_qs.count()

    # Pre-count rows that must receive a vector (same skip rules as the loop).
    embeddable = 0
    for helper in helpers_qs.iterator(chunk_size=500):
        if _is_discontinued(helper.Status):
            continue
        if not str(helper.Product_ID or "").strip():
            continue
        if not helper_document(helper).strip():
            continue
        embeddable += 1

    if not is_configured():
        if require_success and embeddable > 0:
            raise AIServiceError(
                "OPENAI_API_KEY is required to generate embeddings before the "
                "database import can succeed."
            )
        logger.info(
            "Embedding generation skipped for version %s because AI is disabled.",
            database_version_id,
        )
        return {"total": total, "generated": 0, "skipped": total, "errors": 0}

    try:
        DatabaseVersion.objects.get(pk=database_version_id)
    except DatabaseVersion.DoesNotExist as exc:
        logger.error(
            "DatabaseVersion %s not found for embedding generation",
            database_version_id,
        )
        if require_success:
            raise AIServiceError(
                f"Database version {database_version_id} not found for embeddings."
            ) from exc
        return {"total": 0, "generated": 0, "skipped": 0, "errors": 1}

    generated = skipped = errors = 0
    store = ChromaEmbeddingStore()
    # Clear only this version's prior vectors (safe retry); keep other versions
    # until import activates and calls replace_embeddings_with_version.
    store.reset_version(database_version_id)

    pending_helpers: list[Product_Helper] = []
    pending_texts: list[str] = []
    batch_size = _embedding_batch_size()

    for helper in helpers_qs.iterator(chunk_size=batch_size):
        if _is_discontinued(helper.Status):
            skipped += 1
            continue
        if not str(helper.Product_ID or "").strip():
            skipped += 1
            continue
        text = helper_document(helper)
        if not text.strip():
            skipped += 1
            continue

        pending_helpers.append(helper)
        pending_texts.append(text)
        if len(pending_helpers) < batch_size:
            continue

        batch_generated, batch_errors = _index_helper_batch(
            store, pending_helpers, pending_texts
        )
        generated += batch_generated
        errors += batch_errors
        pending_helpers = []
        pending_texts = []

    if pending_helpers:
        batch_generated, batch_errors = _index_helper_batch(
            store, pending_helpers, pending_texts
        )
        generated += batch_generated
        errors += batch_errors

    summary = {
        "total": total,
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "embeddable": embeddable,
    }
    logger.info(
        "Product_Helper embedding summary for version %s: %s",
        database_version_id,
        summary,
    )

    if require_success:
        if errors > 0:
            store.reset_version(database_version_id)
            raise AIServiceError(
                f"Embedding generation failed for {errors} Product_Helper row(s). "
                "Database import was not activated."
            )
        if embeddable > 0 and generated != embeddable:
            store.reset_version(database_version_id)
            raise AIServiceError(
                f"Embedding generation incomplete ({generated}/{embeddable}). "
                "Database import was not activated."
            )

    return summary


def replace_embeddings_with_version(database_version_id: int) -> None:
    """After a successful import activate: keep only this version in Chroma."""
    store = ChromaEmbeddingStore()
    other_ids = list(
        DatabaseVersion.objects.exclude(pk=database_version_id).values_list(
            "pk", flat=True
        )
    )
    for version_id in other_ids:
        store.reset_version(int(version_id))
    logger.info(
        "Chroma now holds embeddings for database version %s only "
        "(%s other version(s) cleared)",
        database_version_id,
        len(other_ids),
    )