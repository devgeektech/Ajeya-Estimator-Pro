"""Tests for the accounts app (custom User + authentication flow)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from common.choices import UserRole

User = get_user_model()

class UserModelTests(TestCase):
    def test_create_user_defaults_to_expert(self):
        user = User.objects.create_user("expert@example.com", "pass12345")
        self.assertEqual(user.role, UserRole.EXPERT)
        self.assertTrue(user.is_expert)
        self.assertFalse(user.is_admin)
        self.assertFalse(user.is_staff)

    def test_create_superuser_is_superadmin(self):
        admin = User.objects.create_superuser("admin@example.com", "pass12345")
        self.assertEqual(admin.role, UserRole.SUPERADMIN)
        self.assertTrue(admin.is_superadmin)
        self.assertFalse(admin.is_admin)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_email_is_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_user("", "pass12345")

    def test_email_is_lowercased_on_save(self):
        user = User.objects.create_user("MixedCase@Example.COM", "pass12345")
        self.assertEqual(user.email, "mixedcase@example.com")

    def test_full_name_falls_back_to_email(self):
        user = User.objects.create_user("noname@example.com", "pass12345")
        self.assertEqual(user.full_name, "noname@example.com")
        user.first_name = "Ada"
        user.last_name = "Lovelace"
        self.assertEqual(user.full_name, "Ada Lovelace")


class AuthFlowTests(TestCase):
    def test_login_page_renders(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_valid_login_redirects_to_dashboard(self):
        User.objects.create_user("expert@example.com", "pass12345")
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "expert@example.com", "password": "pass12345"},
        )
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_login_normalizes_email_case(self):
        User.objects.create_user("expert@example.com", "pass12345")
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "EXPERT@EXAMPLE.COM", "password": "pass12345"},
        )
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_invalid_login_shows_error(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"email": "nobody@example.com", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")

    def test_authenticated_pages_are_not_cached(self):
        user = User.objects.create_user("expert@example.com", "pass12345")
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_password_reset_rejects_unregistered_email(self):
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "missing@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This email is not registered.")

    def test_password_reset_accepts_registered_email_case_insensitively(self):
        User.objects.create_user("expert@example.com", "pass12345")
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "EXPERT@EXAMPLE.COM"},
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))


class ProfileTests(TestCase):
    def test_expert_can_update_profile_name(self):
        user = User.objects.create_user("expert@example.com", "pass12345")
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Expert",
                "last_name": "User",
                "profile_submit": "1",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.full_name, "Expert User")

    def test_admin_can_update_profile_name(self):
        user = User.objects.create_user(
            "admin@example.com", "pass12345", role=UserRole.ADMIN
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Platform",
                "last_name": "Admin",
                "profile_submit": "1",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.full_name, "Platform Admin")

    def test_user_can_update_password_from_profile(self):
        user = User.objects.create_user("expert@example.com", "pass12345")
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "old_password": "pass12345",
                "new_password1": "newpass12345",
                "new_password2": "newpass12345",
                "password_submit": "1",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("newpass12345"))
