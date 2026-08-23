from django.test import TestCase, Client
from unittest.mock import patch
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.boq.models import BOQ
from common.choices import BOQStatus

User = get_user_model()

class BOQViewsUITestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(email="test@example.com", password="password")  # type: ignore
        self.client.login(email="test@example.com", password="password")
        
        self.boq = BOQ.objects.create(
            boq_name="UI Test BOQ",
            status=BOQStatus.MATCHING,
            boq_data={"rows": []},
            analysis_data={"rows": []},
            user=self.user
        )

    def test_analysis_view_renders_correctly(self):
        url = reverse("boq:detail", args=[self.boq.id])
        response = self.client.get(url)
        if response.status_code == 302:
            print("Redirected to:", getattr(response, "url", ""))
        self.assertEqual(response.status_code, 200)
        
        # Verify essential UI elements are in the context or HTML
        self.assertContains(response, "Ajeya Estimator Pro")
        # Ensure it loads the analysis template
        self.assertTemplateUsed(response, "boq/boq_detail.html")

    def test_export_guarded_before_ready(self):
        url = reverse("boq:export", args=[self.boq.id])
        response = self.client.get(url)
        # Should redirect or show an error because status is MAPPING, not READY_EXPORT
        self.assertNotEqual(response.status_code, 200)

    @patch("apps.boq.views.BOQExportService")
    def test_export_allowed_when_ready(self, mock_export_service):
        mock_instance = mock_export_service.return_value
        mock_instance.run.return_value = (b"dummy excel", "dummy.xlsx")
        
        self.boq.status = BOQStatus.READY_EXPORT
        self.boq.save()
        url = reverse("boq:export", args=[self.boq.id])
        response = self.client.get(url)
        if response.status_code == 302:
            print("Redirected to:", getattr(response, "url", ""))
        # The export view returns a file download (HttpResponse with content_type)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
