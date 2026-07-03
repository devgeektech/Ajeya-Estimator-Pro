"""Celery task: send user notifications (scaffold)."""
from celery import shared_task


@shared_task(name="send_notification_task")
def send_notification_task(user_id: int, title: str, message: str = ""):
    from apps.notifications.models import Notification

    return Notification.objects.create(  # type: ignore[attr-defined]
        user_id=user_id, title=title, message=message
    ).pk
