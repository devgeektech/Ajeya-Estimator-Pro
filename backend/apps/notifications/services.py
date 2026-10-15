"""Notification service — create and query in-app user notifications."""
from __future__ import annotations

import logging

from apps.notifications.models import Notification

logger = logging.getLogger("boq_ai")


MAX_NOTIFICATIONS_PER_USER = 50


def prune_notifications_for_user(user, limit: int = MAX_NOTIFICATIONS_PER_USER) -> int:
    """Retain only the most recent `limit` notifications for the given user, deleting older entries."""
    if user is None:
        return 0
    qs = Notification.objects.filter(user=user)
    keep_ids = list(
        qs.order_by("-created_at", "-id").values_list("id", flat=True)[:limit]
    )
    if not keep_ids:
        return 0
    deleted, _ = qs.exclude(id__in=keep_ids).delete()
    return deleted


def prune_all_notifications(limit: int = MAX_NOTIFICATIONS_PER_USER) -> int:
    """Prune notifications across all users to keep only the recent `limit` per user."""
    total_deleted = 0
    user_ids = list(
        Notification.objects.values_list("user_id", flat=True).distinct()
    )
    for uid in user_ids:
        qs = Notification.objects.filter(user_id=uid)
        keep_ids = list(
            qs.order_by("-created_at", "-id").values_list("id", flat=True)[:limit]
        )
        if keep_ids:
            deleted, _ = qs.exclude(id__in=keep_ids).delete()
            total_deleted += deleted
    return total_deleted


def notify(user, title: str, message: str = ""):
    """Create a notification for a user and enforce the 50 recent entries queue. Returns it (or None on failure)."""
    if user is None:
        return None

    try:
        notif = Notification.objects.create(user=user, title=title, message=message)
        prune_notifications_for_user(user, limit=MAX_NOTIFICATIONS_PER_USER)
        return notif
    except Exception:  # noqa: BLE001 - notifications must not break core flows
        logger.exception("Failed to create notification for %s", getattr(user, "pk", None))
        return None


def unread_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0

    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_read(user) -> int:
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)


def mark_selected_read(user, ids: list[int]) -> int:
    """Mark selected notifications as read. Returns updated count."""
    if not ids:
        return 0
    return Notification.objects.filter(
        user=user, pk__in=ids, is_read=False
    ).update(is_read=True)


def clear_all(user) -> int:
    """Delete all notifications for the user. Returns deleted count."""
    deleted, _ = Notification.objects.filter(user=user).delete()
    return deleted


def clear_selected(user, ids: list[int]) -> int:
    """Delete selected notifications owned by the user. Returns deleted count."""
    if not ids:
        return 0
    deleted, _ = Notification.objects.filter(user=user, pk__in=ids).delete()
    return deleted
