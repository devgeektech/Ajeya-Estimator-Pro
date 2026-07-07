"""Product-match validation helpers."""
from __future__ import annotations

from utils.text import normalize


def validate_match(description: str, candidate: str) -> dict:
    """Return a simple deterministic validation payload for a candidate match."""
    description_norm = normalize(description)
    candidate_norm = normalize(candidate)
    is_match = bool(candidate_norm and candidate_norm in description_norm)
    return {
        "is_match": is_match,
        "confidence": 100 if is_match else 0,
        "reason": "candidate text found in description" if is_match else "candidate text not found",
    }
