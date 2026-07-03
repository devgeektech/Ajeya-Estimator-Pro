"""Text helpers shared across services."""
from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Lowercase, strip and collapse internal whitespace for comparison."""
    if not text:
        return ""
    return _WHITESPACE.sub(" ", str(text).strip().lower())
