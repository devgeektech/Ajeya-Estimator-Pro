"""Audit visibility: Admin sees self + own Experts; Superadmin sees all."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditLog
from common.choices import UserRole

User = get_user_model()


class AuditScopeTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            email="super@example.com", password="password"
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )
        self.admin2 = User.objects.create_user(
            email="admin2@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )
        self.expert = User.objects.create_user(
            email="expert@example.com",
            password="password",
            role=UserRole.EXPERT,
            created_by=self.admin,
        )
        self.expert2 = User.objects.create_user(
            email="expert2@example.com",
            password="password",
            role=UserRole.EXPERT,
            created_by=self.admin2,
        )
        AuditLog.objects.create(user=self.admin, action="login", entity="User")
        AuditLog.objects.create(user=self.expert, action="boq_upload", entity="BOQ")
        AuditLog.objects.create(user=self.admin2, action="login", entity="User")
        AuditLog.objects.create(user=self.expert2, action="boq_upload", entity="BOQ")

    def test_admin_audit_list_shows_self_and_own_experts(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.get(reverse("audit:list"))
        self.assertEqual(response.status_code, 200)
        emails = {u.email for u in response.context["users"]}
        self.assertEqual(emails, {"admin@example.com", "expert@example.com"})

    def test_admin_can_open_own_expert_audit(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.get(reverse("audit:user_list", args=[self.expert.pk]))
        self.assertEqual(response.status_code, 200)

    def test_admin_cannot_open_peer_admin_or_other_expert_audit(self):
        self.client.login(email="admin@example.com", password="password")
        self.assertEqual(
            self.client.get(reverse("audit:user_list", args=[self.admin2.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("audit:user_list", args=[self.expert2.pk])).status_code,
            404,
        )

    def test_superadmin_sees_admins_and_experts(self):
        self.client.login(email="super@example.com", password="password")
        response = self.client.get(reverse("audit:list"))
        self.assertEqual(response.status_code, 200)
        emails = {u.email for u in response.context["users"]}
        self.assertIn("admin@example.com", emails)
        self.assertIn("admin2@example.com", emails)
        self.assertIn("expert@example.com", emails)
        self.assertIn("expert2@example.com", emails)
