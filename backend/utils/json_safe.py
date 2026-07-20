"""JSON-safe serialization helpers for Django JSONField payloads."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone


def json_safe(value: Any) -> Any:
    """Recursively convert values to JSON-serializable forms."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)
