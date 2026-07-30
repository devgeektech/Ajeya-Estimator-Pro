"""Project clock helpers — all display/storage timestamps use IST."""
from __future__ import annotations

from datetime import datetime

from django.utils import timezone


def now_local() -> datetime:
    """Current time in Django ``TIME_ZONE`` (Asia/Kolkata / IST)."""
    return timezone.localtime(timezone.now())


def now_local_iso() -> str:
    """ISO-8601 timestamp in IST (includes ``+05:30`` offset)."""
    return now_local().isoformat()
