import os
import io
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch
from apps.boq.models import BOQ
from common.choices import BOQStatus
from openpyxl import Workbook

User = get_user_model()

class BOQUploadTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(email="test@example.com", password="password")  # type: ignore
        self.client.login(email="test@example.com", password="password")

    def _create_mock_excel(self) -> bytes:
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "BOQ"
        ws.append(["Sr No", "Item Description", "Qty", "Unit", "Rate", "Amount"])
        ws.append(["1", "Fire Pump 1000GPM", "1", "Nos", "", ""])
        buffer = io.BytesIO()
        wb.save(buffer)
        return buffer.getvalue()

    @patch("apps.database_manager.services.activation.get_active_database_version")
    def test_upload_boq_success(self, mock_get_active):
        mock_get_active.return_value = 1
        url = reverse("boq:upload")
        excel_data = self._create_mock_excel()
        excel_file = SimpleUploadedFile(
            "test_boq.xlsx",
            excel_data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response = self.client.post(url, {"uploaded_file": excel_file, "boq_name": "Test BOQ"}, follow=True)
        self.assertEqual(response.status_code, 200)
        
        # Verify BOQ was created
        boqs = BOQ.objects.all()
        self.assertEqual(boqs.count(), 1)
        boq = boqs.first()
        assert boq is not None
        self.assertEqual(boq.status, BOQStatus.UPLOADED)
        self.assertIn("Fire Pump 1000GPM", str(boq.boq_data))

    def test_upload_invalid_file(self):
        url = reverse("boq:upload")
        bad_file = SimpleUploadedFile("test.txt", b"not an excel", content_type="text/plain")
        response = self.client.post(url, {"uploaded_file": bad_file, "boq_name": "Test Bad BOQ"}, follow=True)
        # Assuming the form catches it and redirects or shows an error in the template
        # The exact response depends on the view, but the BOQ shouldn't be created.
        self.assertEqual(BOQ.objects.count(), 0)
