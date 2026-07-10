"""Notification service — create and query in-app user notifications."""
from __future__ import annotations

import logging

from apps.notifications.models import Notification

logger = logging.getLogger("boq_ai")


def notify(user, title: str, message: str = ""):
    """Create a notification for a user. Returns it (or None on failure)."""
    if user is None:
        return None

    try:
        return Notification.objects.create(user=user, title=title, message=message)
    except Exception:  # noqa: BLE001 - notifications must not break core flows
        logger.exception("Failed to create notification for %s", getattr(user, "pk", None))
        return None


def unread_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0

    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_read(user) -> int:
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)
