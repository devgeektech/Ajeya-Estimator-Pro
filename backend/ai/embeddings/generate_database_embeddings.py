"""Synchronous embedding generation for imported master database versions."""
import logging

from ai.embeddings.generator import generate_embedding
from ai.openai_client import is_configured
from apps.database_manager.models import DatabaseVersion, ProductEmbedding, RateMaster
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

    for product in products.iterator():
        text = " ".join(
            part
            for part in (product.product_code, product.description, product.make, product.unit)
            if part
        )
        if not text.strip():
            skipped += 1
            continue

        if ProductEmbedding.objects.filter(product_code=product.product_code).exists():
            skipped += 1
            continue

        try:
            vector = generate_embedding(text)
            ProductEmbedding.objects.update_or_create(
                product_code=product.product_code,
                defaults={"embedding_vector": vector},
            )
            generated += 1
        except AIServiceError:
            logger.exception("Embedding failed for RateMaster row %s", product.pk)
            errors += 1

    summary = {"total": total, "generated": generated, "skipped": skipped, "errors": errors}
    logger.info("Embedding generation summary for version %s: %s", database_version_id, summary)
    return summary
