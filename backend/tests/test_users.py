"""Tests for Super Admin user management access control."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from common.choices import UserRole

User = get_user_model()


class UserManagementAccessTests(TestCase):
    def setUp(self):
        self.dev = User.objects.create_superuser("dev@example.com", "pass12345")
        self.admin = User.objects.create_user(
            "admin@example.com", "pass12345", role=UserRole.ADMIN
        )
        self.expert = User.objects.create_user("expert@example.com", "pass12345")

    def test_expert_cannot_access_user_list(self):
        self.client.force_login(self.expert)
        response = self.client.get(reverse("users:list"))
        self.assertEqual(response.status_code, 403)

    def test_super_admin_can_access_user_list(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("users:list"))
        self.assertEqual(response.status_code, 200)

    def test_developer_superuser_is_hidden_from_user_list(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("users:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "dev@example.com")

    def test_logged_in_admin_is_hidden_from_user_list(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("users:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<td>admin@example.com</td>", html=True)

    def test_super_admin_can_create_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("users:create"),
            {
                "email": "new@example.com",
                "first_name": "New",
                "last_name": "User",
                "role": "EXPERT",
                "is_active": "on",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
            },
        )
        self.assertRedirects(response, reverse("users:list"))
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.role, UserRole.EXPERT)

    def test_admin_role_always_has_db_access(self):
        admin = User.objects.create_user(
            "locked-admin@example.com",
            "pass12345",
            role=UserRole.ADMIN,
            allow_db_access=False,
        )
        self.assertTrue(admin.allow_db_access)

        admin.allow_db_access = False
        admin.save(update_fields=["allow_db_access"])
        admin.refresh_from_db()
        self.assertTrue(admin.allow_db_access)

    def test_admin_db_access_cannot_be_toggled_off(self):
        target = User.objects.create_user(
            "target-admin@example.com",
            "pass12345",
            role=UserRole.ADMIN,
            allow_db_access=False,
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("users:toggle_db_access", args=[target.pk]))
        self.assertRedirects(response, reverse("users:list"))
        target.refresh_from_db()
        self.assertTrue(target.allow_db_access)

    def test_admin_cannot_deactivate_self_from_user_management(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("users:toggle_active", args=[self.admin.pk]))
        self.assertEqual(response.status_code, 404)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_cannot_edit_self_from_user_management(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("users:edit", args=[self.admin.pk]))
        self.assertEqual(response.status_code, 404)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, "admin@example.com")
        self.assertEqual(self.admin.role, "ADMIN")

    def test_admin_cannot_promote_other_user_to_admin(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("users:edit", args=[self.expert.pk]),
            {
                "email": "changed@example.com",
                "first_name": "Expert",
                "last_name": "User",
                "role": "ADMIN",
            },
        )
        self.assertRedirects(response, reverse("users:list"))
        self.expert.refresh_from_db()
        self.assertEqual(self.expert.email, "changed@example.com")
        self.assertEqual(self.expert.role, UserRole.EXPERT)

    def test_app_cannot_edit_developer_superuser(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("users:edit", args=[self.dev.pk]))
        self.assertEqual(response.status_code, 404)

    def test_platform_admin_cannot_access_django_admin(self):
        self.client.force_login(self.admin)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_superadmin_can_access_django_admin(self):
        self.client.force_login(self.dev)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_super_admin_can_delete_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("users:delete", args=[self.expert.pk]))
        self.assertRedirects(response, reverse("users:list"))
        self.assertFalse(User.objects.filter(pk=self.expert.pk).exists())

    def test_admin_cannot_delete_self_from_user_management(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("users:delete", args=[self.admin.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_expert_cannot_delete_user(self):
        self.client.force_login(self.expert)
        response = self.client.post(reverse("users:delete", args=[self.admin.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
