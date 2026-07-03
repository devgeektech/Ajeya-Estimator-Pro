"""Celery task: generate product embeddings for a master database version.

Invoked by the database import workflow after a new version is activated so
that vector-based product matching (cosine similarity) is available immediately.
Long-running — must not block views (docs/AGENTS.md - Background Jobs).

The task is idempotent: items whose embedding already exists are skipped, so
re-queuing after a partial failure is safe.
"""
import logging

from celery import shared_task

from ai.embeddings.generator import generate_embedding
from ai.openai_client import is_configured
from apps.database_manager.models import DatabaseVersion, ProductEmbedding, RateMaster
from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")


@shared_task(name="generate_embeddings_task")
def generate_embeddings_task(database_version_id: int) -> dict:
    """Generate OpenAI embeddings for every RateMaster row in a database version.

    Returns a summary dict: {"total": int, "generated": int, "skipped": int, "errors": int}.
    When AI is disabled (placeholder key) the task logs and exits gracefully
    without raising so the import pipeline still completes.
    """
    if not is_configured():
        logger.info(
            "generate_embeddings_task: AI disabled (placeholder key) — "
            "skipping embedding generation for version %s",
            database_version_id,
        )
        return {"total": 0, "generated": 0, "skipped": 0, "errors": 0}

    try:
        version = DatabaseVersion.objects.get(pk=database_version_id)
    except DatabaseVersion.DoesNotExist:
        logger.error("generate_embeddings_task: DatabaseVersion %s not found", database_version_id)
        return {"total": 0, "generated": 0, "skipped": 0, "errors": 1}

    products = RateMaster.objects.filter(database_version=version)
    total = products.count()
    generated = skipped = errors = 0

    for product in products.iterator():
        # Build a rich text representation to embed.
        text = " ".join(
            filter(None, [product.product_code, product.description, product.make, product.unit])
        )
        if not text.strip():
            skipped += 1
            continue

        # Skip if an embedding for this product_code already exists (idempotent).
        # ProductEmbedding is keyed only by product_code (no database_version FK in V1).
        if ProductEmbedding.objects.filter(
            product_code=product.product_code
        ).exists():
            skipped += 1
            continue

        try:
            vector = generate_embedding(text)
            # Upsert: product_code is the natural key in V1 (no FK to version).
            ProductEmbedding.objects.update_or_create(
                product_code=product.product_code,
                defaults={"embedding_vector": vector},
            )
            generated += 1
        except AIServiceError:
            logger.exception(
                "generate_embeddings_task: embedding failed for product %s", product.pk
            )
            errors += 1

    logger.info(
        "generate_embeddings_task: version=%s total=%s generated=%s skipped=%s errors=%s",
        database_version_id,
        total,
        generated,
        skipped,
        errors,
    )
    return {"total": total, "generated": generated, "skipped": skipped, "errors": errors}
