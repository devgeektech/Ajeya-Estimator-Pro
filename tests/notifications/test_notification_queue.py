"""Tests for notification queue retention (50 entries per user)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.notifications.models import Notification
from apps.notifications.services import (
    notify,
    prune_all_notifications,
)

User = get_user_model()


class NotificationQueueTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(email="notif_user1@example.com", password="password")
        self.user2 = User.objects.create_user(email="notif_user2@example.com", password="password")

    def test_notify_caps_notifications_at_50_per_user(self):
        for i in range(50):
            notify(user=self.user1, title=f"Notif {i}")

        self.assertEqual(Notification.objects.filter(user=self.user1).count(), 50)
        oldest_entry = (
            Notification.objects.filter(user=self.user1).order_by("created_at", "id").first()
        )
        self.assertEqual(oldest_entry.title, "Notif 0")

        # Adding 51st notification removes oldest
        notify(user=self.user1, title="Notif 50")
        self.assertEqual(Notification.objects.filter(user=self.user1).count(), 50)
        self.assertFalse(Notification.objects.filter(id=oldest_entry.id).exists())

        newest_entry = (
            Notification.objects.filter(user=self.user1).order_by("-created_at", "-id").first()
        )
        self.assertEqual(newest_entry.title, "Notif 50")

    def test_notification_per_user_isolation(self):
        for i in range(50):
            notify(user=self.user1, title=f"U1 Notif {i}")
        for i in range(10):
            notify(user=self.user2, title=f"U2 Notif {i}")

        self.assertEqual(Notification.objects.filter(user=self.user1).count(), 50)
        self.assertEqual(Notification.objects.filter(user=self.user2).count(), 10)

        notify(user=self.user1, title="U1 Extra")
        self.assertEqual(Notification.objects.filter(user=self.user1).count(), 50)
        self.assertEqual(Notification.objects.filter(user=self.user2).count(), 10)

    def test_prune_all_notifications(self):
        entries = [
            Notification(user=self.user1, title=f"Bulk {i}") for i in range(65)
        ]
        Notification.objects.bulk_create(entries)

        self.assertEqual(Notification.objects.filter(user=self.user1).count(), 65)
        deleted = prune_all_notifications(limit=50)
        self.assertEqual(deleted, 15)
        self.assertEqual(Notification.objects.filter(user=self.user1).count(), 50)
