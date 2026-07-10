"""Tests for BOQ upload (upload-only workflow)."""
import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.boq.models import BOQ

User = get_user_model()


def _workbook_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Description", "Unit", "Qty"])
    ws.append(["Pipe", "m", 10])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BOQUploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("expert@example.com", "pass12345")

    def test_upload_page_requires_login(self):
        response = self.client.get(reverse("boq:upload"))
        self.assertEqual(response.status_code, 302)

    def test_upload_creates_boq_record(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            "boq.xlsx",
            _workbook_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response = self.client.post(
            reverse("boq:upload"),
            {"boq_name": "Tower A", "uploaded_file": upload},
        )
        self.assertRedirects(response, reverse("dashboard:home"))
        boq = BOQ.objects.get()
        self.assertEqual(boq.boq_name, "Tower A")
        self.assertEqual(boq.user, self.user)
        self.assertTrue(boq.uploaded_file.name)

    def test_upload_rejects_non_excel(self):
        self.client.force_login(self.user)
        bad = SimpleUploadedFile("boq.csv", b"a,b,c", content_type="text/csv")
        response = self.client.post(
            reverse("boq:upload"),
            {"boq_name": "Bad", "uploaded_file": bad},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BOQ.objects.count(), 0)
