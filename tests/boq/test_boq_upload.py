import io
import json
import time
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch
from apps.boq.models import BOQ
from apps.boq.services.boq_upload_progress import (
    STATUS_PROCESSING,
    begin_upload,
    clear_terminal_upload_status,
    is_upload_busy,
    mark_upload_failed,
    mark_upload_succeeded,
    read_upload_status,
)
from common.choices import BOQStatus
from openpyxl import Workbook

User = get_user_model()


class BOQUploadTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(email="test@example.com", password="password")  # type: ignore
        self.client.login(email="test@example.com", password="password")
        mark_upload_failed(user_id=self.user.pk, message="reset")
        from apps.boq.services import boq_upload_progress as prog

        path = prog._status_path(self.user.pk)
        if path.is_file():
            path.unlink()

    def tearDown(self):
        from apps.boq.services import boq_upload_progress as prog

        path = prog._status_path(self.user.pk)
        if path.is_file():
            path.unlink()

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

    def test_upload_progress_single_flight(self):
        self.assertTrue(begin_upload(user_id=self.user.pk, boq_name="A"))
        self.assertTrue(is_upload_busy(self.user.pk))
        self.assertFalse(begin_upload(user_id=self.user.pk, boq_name="B"))
        mark_upload_succeeded(user_id=self.user.pk, boq_name="A")
        self.assertFalse(is_upload_busy(self.user.pk))
        self.assertEqual(read_upload_status(self.user.pk)["status"], "succeeded")

    def test_clear_terminal_upload_status(self):
        mark_upload_succeeded(user_id=self.user.pk, boq_name="Old")
        self.assertEqual(read_upload_status(self.user.pk)["status"], "succeeded")
        clear_terminal_upload_status(self.user.pk)
        self.assertEqual(read_upload_status(self.user.pk)["status"], "idle")
        begin_upload(user_id=self.user.pk, boq_name="Live")
        clear_terminal_upload_status(self.user.pk)
        self.assertEqual(read_upload_status(self.user.pk)["status"], STATUS_PROCESSING)

    def test_terminal_status_expires_to_idle(self):
        mark_upload_succeeded(user_id=self.user.pk, boq_name="Old")
        from apps.boq.services import boq_upload_progress as prog

        path = prog._status_path(self.user.pk)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["finished_at"] = time.time() - (prog._TERMINAL_STATUS_TTL_SECONDS + 5)
        data["updated_at"] = data["finished_at"]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(read_upload_status(self.user.pk)["status"], "idle")
        self.assertFalse(path.is_file())

    def test_stale_processing_auto_fails(self):
        begin_upload(user_id=self.user.pk, boq_name="Stuck")
        from apps.boq.services import boq_upload_progress as prog

        path = prog._status_path(self.user.pk)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["updated_at"] = time.time() - (prog._STALE_PROCESSING_SECONDS + 5)
        path.write_text(json.dumps(data), encoding="utf-8")
        status = read_upload_status(self.user.pk)
        self.assertEqual(status["status"], "failed")
        self.assertFalse(is_upload_busy(self.user.pk))

    @patch("apps.database_manager.services.activation.get_active_database_version")
    def test_upload_get_clears_stale_succeeded(self, mock_get_active):
        mock_get_active.return_value = 1
        mark_upload_succeeded(user_id=self.user.pk, boq_name="Stale")
        response = self.client.get(reverse("boq:upload"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(read_upload_status(self.user.pk)["status"], "idle")

    def test_upload_status_endpoint(self):
        begin_upload(user_id=self.user.pk, boq_name="Busy")
        response = self.client.get(reverse("boq:upload_status"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["busy"])
        self.assertEqual(data["status"], STATUS_PROCESSING)

    @patch("apps.database_manager.services.activation.get_active_database_version")
    def test_list_shows_uploading_when_busy(self, mock_get_active):
        mock_get_active.return_value = 1
        begin_upload(user_id=self.user.pk, boq_name="Busy")
        response = self.client.get(reverse("boq:list"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["upload_busy"])
        self.assertContains(response, "Uploading")
