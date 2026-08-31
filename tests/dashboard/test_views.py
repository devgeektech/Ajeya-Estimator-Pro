from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.boq.models import BOQ
from common.choices import BOQStatus, UserRole

User = get_user_model()

class DashboardViewsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com", password="password", role=UserRole.EXPERT
        )

    def test_dashboard_home_redirects_if_unauthenticated(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertRedirects(response, f"/login/?next={reverse('dashboard:home')}")

    def test_dashboard_home_loads_for_authenticated_user(self):
        self.client.login(email="test@example.com", password="password")
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)

    def test_recent_boqs_show_view_and_delete_actions(self):
        boq = BOQ.objects.create(
            user=self.user,
            boq_name="Dash BOQ",
            status=BOQStatus.UPLOADED,
        )
        self.client.login(email="test@example.com", password="password")
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("boq:detail", args=[boq.pk]))
        self.assertContains(response, reverse("boq:delete", args=[boq.pk]))
        self.assertContains(response, "topbar-view")
        self.assertContains(response, "topbar-delete")
        self.assertNotContains(response, "btn--open")
