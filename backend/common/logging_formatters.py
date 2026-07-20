"""Logging formatters that emit timestamps in project TIME_ZONE (IST)."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings


class LocalTimeFormatter(logging.Formatter):
    """Format ``asctime`` in Django ``TIME_ZONE`` (default Asia/Kolkata)."""

    def formatTime(self, record, datefmt=None):
        tz_name = getattr(settings, "TIME_ZONE", "Asia/Kolkata")
        dt = datetime.fromtimestamp(record.created, tz=ZoneInfo(tz_name))
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
