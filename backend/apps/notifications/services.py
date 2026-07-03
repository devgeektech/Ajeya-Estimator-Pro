"""Notification service (Phase 11, Sprint 20).

Creates and queries user notifications for key events: processing completion /
failure, ready-for-review and export completion (docs/PRD.md - Notifications).
Kept defensive so notification failures never break core flows.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("boq_ai")


def notify(user, title: str, message: str = ""):
    """Create a notification for a user. Returns it (or None on failure)."""
    if user is None:
        return None
    from apps.notifications.models import Notification

    try:
        return Notification.objects.create(user=user, title=title, message=message)
    except Exception:  # noqa: BLE001 - notifications must not break core flows
        logger.exception("Failed to create notification for %s", getattr(user, "pk", None))
        return None


def unread_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    from apps.notifications.models import Notification

    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_read(user) -> int:
    from apps.notifications.models import Notification

    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)
