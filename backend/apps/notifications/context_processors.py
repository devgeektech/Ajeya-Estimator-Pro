"""Template context for notifications (unread badge in the nav)."""
from __future__ import annotations

from apps.notifications.services import unread_count


def notifications(request):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {"notifications_unread": 0}
    return {"notifications_unread": unread_count(user)}
