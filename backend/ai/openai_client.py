"""Thin OpenAI client wrapper.

Centralises OpenAI access so models and error handling live in one place.
"""

from __future__ import annotations

import logging

from django.conf import settings
from openai import OpenAI

from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")

# A key matching any of these (case-insensitive) is treated as a placeholder
# and AI features stay disabled (graceful degradation).
_PLACEHOLDER_MARKERS = ("replace", "your-", "your_", "changeme", "xxxx", "placeholder")


def is_configured() -> bool:
    """True only when a real (non-placeholder) API key is set."""
    key = (settings.OPENAI_API_KEY or "").strip()
    if not key:
        return False
    lowered = key.lower()
    return not any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def get_client():
    """Return a configured OpenAI client."""
    if not is_configured():
        raise AIServiceError("OPENAI_API_KEY is not configured (placeholder in use).")
    return OpenAI(
        api_key=str(settings.OPENAI_API_KEY),
        timeout=(
            float(settings.OPENAI_TIMEOUT_SECONDS)
            if getattr(settings, "OPENAI_TIMEOUT_SECONDS", None)
            else None
        ),
        max_retries=int(getattr(settings, "OPENAI_MAX_RETRIES", 1)),
    )
