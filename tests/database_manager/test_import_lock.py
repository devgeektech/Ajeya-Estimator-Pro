"""Global database import lock and status endpoint."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from common.choices import UserRole
from apps.database_manager.services.database_import_progress import (
    STATUS_PROCESSING,
    is_import_busy,
    mark_import_failed,
    mark_import_succeeded,
    read_import_status,
    try_begin_import,
)

User = get_user_model()


class DatabaseImportProgressTests(TestCase):
    def setUp(self):
        mark_import_failed("reset")
        from apps.database_manager.services import database_import_progress as prog

        if prog._status_path().is_file():
            prog._status_path().unlink()
        prog._release_lock_file()

    def tearDown(self):
        from apps.database_manager.services import database_import_progress as prog

        prog._release_lock_file()
        if prog._status_path().is_file():
            prog._status_path().unlink()

    def test_single_flight_lock(self):
        self.assertTrue(
            try_begin_import(
                uploaded_by_id=1,
                uploaded_by_email="a@example.com",
                filename="a.xlsx",
            )
        )
        self.assertTrue(is_import_busy())
        self.assertFalse(
            try_begin_import(
                uploaded_by_id=2,
                uploaded_by_email="b@example.com",
                filename="b.xlsx",
            )
        )
        mark_import_succeeded(version_number=1)
        self.assertFalse(is_import_busy())
        self.assertEqual(read_import_status()["status"], "succeeded")


class DatabaseImportDispatchViewTests(TestCase):
    def setUp(self):
        from apps.database_manager.services import database_import_progress as prog

        prog._release_lock_file()
        if prog._status_path().is_file():
            prog._status_path().unlink()

        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )

    def tearDown(self):
        from apps.database_manager.services import database_import_progress as prog

        prog._release_lock_file()
        if prog._status_path().is_file():
            prog._status_path().unlink()

    def test_status_endpoint(self):
        self.client.login(email="admin@example.com", password="password")
        response = self.client.get(reverse("database:import_status"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("status", response.json())

    @patch("apps.database_manager.views.run_database_import")
    def test_second_upload_rejected_while_busy(self, mock_run):
        self.assertTrue(
            try_begin_import(
                uploaded_by_id=self.admin.pk,
                uploaded_by_email=self.admin.email,
                filename="first.xlsx",
            )
        )
        self.assertEqual(read_import_status()["status"], STATUS_PROCESSING)

        self.client.login(email="admin@example.com", password="password")
        workbook = SimpleUploadedFile(
            "second.xlsx",
            b"not-a-real-workbook",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response = self.client.post(
            reverse("database:upload"),
            {"name": "Second", "workbook": workbook},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already in progress")
        mock_run.assert_not_called()
