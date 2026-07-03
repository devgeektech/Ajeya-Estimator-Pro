"""Confidence validation helpers (scaffold - Phase 5)."""
from __future__ import annotations

from common.constants import confidence_band


def band_for(score: float) -> str:
    """Return the colour band for a confidence score."""
    return confidence_band(score)
