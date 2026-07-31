"""File-handling helpers."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from django.utils import timezone


def unique_filename(original_name: str) -> str:
    """Return a collision-resistant filename preserving the extension."""
    suffix = Path(original_name).suffix
    return f"{uuid.uuid4().hex}{suffix}"


def stamped_upload_filename(
    original_name: str,
    when: datetime | None = None,
) -> str:
    """Rename a stored upload as ``{stem}_{YYYYMMDD_HHMMSS}{suffix}``.

    Display/download still uses the original ``source_filename`` separately.
    """
    path = Path(original_name)
    stem = re.sub(r"[^\w\-]+", "_", path.stem).strip("_") or "upload"
    stamp = (when or timezone.now()).strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{stamp}{path.suffix}"
