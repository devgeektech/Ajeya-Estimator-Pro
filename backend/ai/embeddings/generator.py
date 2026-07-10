"""Embedding generation for master database products."""
from __future__ import annotations

import logging

from django.conf import settings

from common.exceptions import AIServiceError

from ai.openai_client import get_client

logger = logging.getLogger("boq_ai")


def generate_embedding(text: str) -> list[float]:
    """Return the embedding vector for ``text``.

    Raises AIServiceError when AI is disabled so callers can skip gracefully.
    """
    client = get_client()
    try:
        kwargs = {
            "model": str(settings.OPENAI_EMBEDDING_MODEL),
            "input": text,
        }
        dimensions = int(getattr(settings, "OPENAI_EMBEDDING_DIMENSIONS", 1536) or 0)
        if dimensions:
            kwargs["dimensions"] = dimensions
        response = client.embeddings.create(**kwargs)
        return list(response.data[0].embedding)
    except AIServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise provider errors
        logger.exception("Embedding generation failed")
        raise AIServiceError(f"Embedding request failed: {exc}") from exc
