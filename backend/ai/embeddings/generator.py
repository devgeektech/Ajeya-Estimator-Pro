"""Embedding generation (Phase 5).

Generates embeddings for products and product aliases only
(docs/DATABASE_ARCHITECTURE.md - Embedding Strategy). Used by vector matching
to find candidate products when exact/alias matching fails.
"""
from __future__ import annotations

import logging

from django.conf import settings

from common.exceptions import AIServiceError

from ai.openai_client import get_client

logger = logging.getLogger("boq_ai")


def generate_embedding(text: str) -> list[float]:
    """Return the embedding vector for ``text``.

    Raises AIServiceError when AI is disabled (placeholder key) so callers can
    skip vector matching gracefully.
    """
    client = get_client()
    try:
        response = client.embeddings.create(
            model=str(settings.OPENAI_EMBEDDING_MODEL),
            input=text,
        )
        return list(response.data[0].embedding)
    except AIServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise provider errors
        logger.exception("Embedding generation failed")
        raise AIServiceError(f"Embedding request failed: {exc}") from exc
