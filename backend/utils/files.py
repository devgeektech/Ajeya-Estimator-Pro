"""File-handling helpers."""
from __future__ import annotations

import uuid
from pathlib import Path


def unique_filename(original_name: str) -> str:
    """Return a collision-resistant filename preserving the extension."""
    suffix = Path(original_name).suffix
    return f"{uuid.uuid4().hex}{suffix}"
