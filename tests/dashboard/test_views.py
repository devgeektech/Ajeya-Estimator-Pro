from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

class DashboardViewsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="password")

    def test_dashboard_home_redirects_if_unauthenticated(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertRedirects(response, f"/login/?next={reverse('dashboard:home')}")

    def test_dashboard_home_loads_for_authenticated_user(self):
        self.client.login(email="test@example.com", password="password")
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
