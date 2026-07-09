"""Synchronous embedding generation for imported master database versions."""
import logging

from ai.embeddings.generator import generate_embedding
from ai.embeddings.chroma_store import ChromaEmbeddingStore, rate_document
from ai.openai_client import is_configured
from apps.database_manager.models import DatabaseVersion, RateMaster
from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")


def generate_embeddings_for_version(database_version_id: int) -> dict:
    """Generate product embeddings for every RateMaster row in a database version."""
    if not is_configured():
        logger.info(
            "Embedding generation skipped for version %s because AI is disabled.",
            database_version_id,
        )
        return {"total": 0, "generated": 0, "skipped": 0, "errors": 0}

    try:
        version = DatabaseVersion.objects.get(pk=database_version_id)
    except DatabaseVersion.DoesNotExist:
        logger.error("DatabaseVersion %s not found for embedding generation", database_version_id)
        return {"total": 0, "generated": 0, "skipped": 0, "errors": 1}

    products = RateMaster.objects.filter(database_version=version)
    total = products.count()
    generated = skipped = errors = 0
    store = ChromaEmbeddingStore()
    store.reset_version(version.pk)

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
            logger.exception("Embedding failed for RateMaster row %s", product.pk)
            errors += 1
        except Exception:
            logger.exception("Chroma indexing failed for RateMaster row %s", product.pk)
            errors += 1

    summary = {"total": total, "generated": generated, "skipped": skipped, "errors": errors}
    logger.info("Embedding generation summary for version %s: %s", database_version_id, summary)
    return summary
