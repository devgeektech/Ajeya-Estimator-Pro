"""Tests for audit logging (Sprint 20)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.audit.services import record
from common.choices import UserRole


class AuditServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="u@x.com", password="x")

    def test_record_creates_entry(self):
        record(self.user, "approve", "BOQ", 7)
        log = AuditLog.objects.get()
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.action, "approve")
        self.assertEqual(log.entity, "BOQ")
        self.assertEqual(log.entity_id, "7")

    def test_record_anonymous_user_is_null(self):
        record(AnonymousUser(), "view")
        log = AuditLog.objects.get()
        self.assertIsNone(log.user)


class AuditViewAccessTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(email="a@x.com", password="x")
        self.expert = get_user_model().objects.create_user(
            email="e@x.com", password="x", role=UserRole.EXPERT
        )
        record(self.expert, "approve", "BOQ", 1)

    def test_admin_sees_log(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("audit:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "approve")

    def test_expert_forbidden(self):
        self.client.force_login(self.expert)
        resp = self.client.get(reverse("audit:list"))
        self.assertEqual(resp.status_code, 403)
