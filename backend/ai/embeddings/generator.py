"""OpenAI embedding generation and Chroma indexing for active master database."""
from __future__ import annotations

import logging

from django.conf import settings

from ai.embeddings.chroma_store import ChromaEmbeddingStore, rate_document
from ai.openai_client import get_client, is_configured
from apps.database_manager.models import DatabaseVersion, MaterialRate
from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")


def generate_embedding(text: str) -> list[float]:
    """Return the embedding vector for ``text``.

    Raises AIServiceError when AI is disabled so callers can skip gracefully.
    """
    client = get_client()
    model = str(settings.OPENAI_EMBEDDING_MODEL)
    dimensions = int(getattr(settings, "OPENAI_EMBEDDING_DIMENSIONS", 1536) or 0)
    try:
        if dimensions:
            response = client.embeddings.create(
                model=model,
                input=text,
                dimensions=dimensions,
            )
        else:
            response = client.embeddings.create(model=model, input=text)
        return list(response.data[0].embedding)
    except AIServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise provider errors
        logger.exception("Embedding generation failed")
        raise AIServiceError(f"Embedding request failed: {exc}") from exc


def generate_embeddings_for_version(database_version_id: int) -> dict:
    """Index Rate_Master rows for the active database version into Chroma.

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

    products = MaterialRate.objects.filter(database_version=version)
    total = products.count()
    generated = skipped = errors = 0
    store = ChromaEmbeddingStore()
    store.reset_all()

    for product in products.iterator():
        text = rate_document(product)
        if not text.strip():
            skipped += 1
            continue

        try:
            vector = generate_embedding(text)
            store.upsert_rate(product, vector)
            generated += 1
        except AIServiceError:
            logger.exception("Embedding failed for MaterialRate row %s", product.pk)
            errors += 1
        except Exception:
            logger.exception("Chroma indexing failed for MaterialRate row %s", product.pk)
            errors += 1

    summary = {"total": total, "generated": generated, "skipped": skipped, "errors": errors}
    logger.info("Embedding generation summary for version %s: %s", database_version_id, summary)
    return summary
