from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

class DatabaseManagerViewsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="password")

    def test_list_view_loads_for_authenticated_user(self):
        self.client.login(email="test@example.com", password="password")
        response = self.client.get(reverse("database:list"))
        self.assertEqual(response.status_code, 200)

    def test_upload_view_loads_for_authenticated_user(self):
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.login(email="test@example.com", password="password")
        response = self.client.get(reverse("database:upload"))
        self.assertEqual(response.status_code, 200)
