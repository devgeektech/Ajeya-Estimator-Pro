"""Thin OpenAI client wrapper.

Centralises OpenAI access so prompts, models and error handling live in one
place (docs/AGENTS.md - OpenAI Rules). Business rules must NOT be hardcoded
here; prompts live in ai/prompts/. AI is used only for understanding,
extraction and validation - never pricing or supplier selection
(docs/AGENTS.md - AI Rules).
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from openai import OpenAI

from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

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


def load_prompt(name: str) -> str:
    """Load a prompt template from ai/prompts/."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise AIServiceError(f"Prompt template not found: {name}")
    return path.read_text(encoding="utf-8")


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
