"""Tests for notifications (Sprint 20)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.notifications.models import Notification
from apps.notifications.services import mark_all_read, notify, unread_count


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="u@x.com", password="x")

    def test_notify_creates_record(self):
        n = notify(self.user, "Hello", "World")
        self.assertIsNotNone(n)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertFalse(n.is_read)

    def test_notify_none_user_is_noop(self):
        self.assertIsNone(notify(None, "x"))
        self.assertEqual(Notification.objects.count(), 0)

    def test_unread_count_and_mark_all_read(self):
        notify(self.user, "a")
        notify(self.user, "b")
        self.assertEqual(unread_count(self.user), 2)
        updated = mark_all_read(self.user)
        self.assertEqual(updated, 2)
        self.assertEqual(unread_count(self.user), 0)


class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="u@x.com", password="x")

    def test_list_requires_login(self):
        resp = self.client.get(reverse("notifications:list"))
        self.assertEqual(resp.status_code, 302)

    def test_list_shows_notifications(self):
        notify(self.user, "Processing complete", "ready")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("notifications:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Processing complete")

    def test_mark_all_read_view(self):
        notify(self.user, "a")
        self.client.force_login(self.user)
        resp = self.client.post(reverse("notifications:read"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(unread_count(self.user), 0)
