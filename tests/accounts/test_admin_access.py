"""Django /admin/ is Superadmin-only; others get 404 or app login redirect."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from common.choices import UserRole

User = get_user_model()


class DjangoAdminAccessTests(TestCase):
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
        self.expert = User.objects.create_user(
            email="expert@example.com",
            password="password",
            role=UserRole.EXPERT,
        )
        self.admin_url = reverse("admin:index")

    def test_anonymous_redirects_to_app_login(self):
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertIn("next=", response.url)

    def test_admin_role_gets_404(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, 404)

    def test_expert_gets_404(self):
        self.client.login(email="expert@example.com", password="password")
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, 404)

    def test_superadmin_can_open_admin(self):
        self.client.login(email="super@example.com", password="password")
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, 200)

    def test_admin_login_path_404_for_non_superadmin(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.get(reverse("admin:login"))
        self.assertEqual(response.status_code, 404)
