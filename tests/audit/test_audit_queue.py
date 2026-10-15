"""Tests for audit log queue retention (50 entries per user)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.audit.services import (
    prune_all_audit_logs,
    record,
)

User = get_user_model()


class AuditQueueTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(email="user1@example.com", password="password")
        self.user2 = User.objects.create_user(email="user2@example.com", password="password")

    def test_record_caps_audit_logs_at_50_per_user(self):
        # Create 50 logs for user1
        for i in range(50):
            record(user=self.user1, action=f"action_{i}")

        self.assertEqual(AuditLog.objects.filter(user=self.user1).count(), 50)
        oldest_entry = AuditLog.objects.filter(user=self.user1).order_by("timestamp", "id").first()
        self.assertEqual(oldest_entry.action, "action_0")

        # Adding the 51st entry removes the oldest one
        record(user=self.user1, action="action_50")
        self.assertEqual(AuditLog.objects.filter(user=self.user1).count(), 50)
        self.assertFalse(AuditLog.objects.filter(id=oldest_entry.id).exists())

        newest_entry = AuditLog.objects.filter(user=self.user1).order_by("-timestamp", "-id").first()
        self.assertEqual(newest_entry.action, "action_50")

    def test_audit_logs_per_user_isolation(self):
        # Populate 50 for user1 and 10 for user2
        for i in range(50):
            record(user=self.user1, action=f"user1_action_{i}")
        for i in range(10):
            record(user=self.user2, action=f"user2_action_{i}")

        self.assertEqual(AuditLog.objects.filter(user=self.user1).count(), 50)
        self.assertEqual(AuditLog.objects.filter(user=self.user2).count(), 10)

        # Adding to user1 does not affect user2
        record(user=self.user1, action="user1_action_51")
        self.assertEqual(AuditLog.objects.filter(user=self.user1).count(), 50)
        self.assertEqual(AuditLog.objects.filter(user=self.user2).count(), 10)

    def test_prune_all_audit_logs(self):
        # Manually bulk create 60 logs for user1
        entries = [AuditLog(user=self.user1, action=f"bulk_{i}") for i in range(60)]
        AuditLog.objects.bulk_create(entries)

        self.assertEqual(AuditLog.objects.filter(user=self.user1).count(), 60)
        deleted = prune_all_audit_logs(limit=50)
        self.assertEqual(deleted, 10)
        self.assertEqual(AuditLog.objects.filter(user=self.user1).count(), 50)
