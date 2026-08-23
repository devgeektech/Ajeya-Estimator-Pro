from django.test import TestCase
from django.urls import reverse

class AccountsViewsTestCase(TestCase):
    def test_login_view_loads(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)

    def test_password_reset_view_loads(self):
        response = self.client.get(reverse("accounts:password_reset"))
        self.assertEqual(response.status_code, 200)
