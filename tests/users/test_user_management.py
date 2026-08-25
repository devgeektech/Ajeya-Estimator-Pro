"""User management: Admins manage own Experts; Superadmin manages Admins."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from common.choices import UserRole
from common.mixins import AdminRequiredMixin, SuperAdminRequiredMixin

User = get_user_model()


class MixinGateTests(TestCase):
    def test_superadmin_mixin_rejects_admin(self):
        admin = User.objects.create_user(
            email="admin@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )
        mixin = SuperAdminRequiredMixin()
        mixin.request = type("R", (), {"user": admin})()
        self.assertFalse(mixin.test_func())

    def test_admin_mixin_allows_admin(self):
        admin = User.objects.create_user(
            email="admin2@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )
        mixin = AdminRequiredMixin()
        mixin.request = type("R", (), {"user": admin})()
        self.assertTrue(mixin.test_func())


class UserManagementScopeTests(TestCase):
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

    def test_admin_list_shows_only_own_experts(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.get(reverse("users:list"))
        self.assertEqual(response.status_code, 200)
        emails = {u.email for u in response.context["users"]}
        self.assertEqual(emails, {"expert@example.com"})

    def test_admin_cannot_delete_peer_admin(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.post(
            reverse("users:delete", args=[self.admin2.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(User.objects.filter(pk=self.admin2.pk).exists())

    def test_admin_cannot_create_admin_role(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.post(
            reverse("users:create"),
            {
                "email": "newadmin@example.com",
                "first_name": "New",
                "last_name": "Admin",
                "role": UserRole.ADMIN,
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
                "allow_db_access": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            User.objects.filter(email="newadmin@example.com").exists()
        )

    def test_superadmin_can_create_admin(self):
        self.client.login(email="super@example.com", password="password")
        response = self.client.post(
            reverse("users:create"),
            {
                "email": "newadmin@example.com",
                "first_name": "New",
                "last_name": "Admin",
                "role": UserRole.ADMIN,
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
                "allow_db_access": True,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(email="newadmin@example.com")
        self.assertEqual(created.role, UserRole.ADMIN)
        self.assertEqual(created.created_by_id, self.superadmin.pk)

    def test_admin_can_create_expert(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.post(
            reverse("users:create"),
            {
                "email": "newexpert@example.com",
                "first_name": "New",
                "last_name": "Expert",
                "role": UserRole.EXPERT,
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
                "allow_db_access": False,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(email="newexpert@example.com")
        self.assertEqual(created.created_by_id, self.admin.pk)
