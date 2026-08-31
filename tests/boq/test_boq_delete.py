"""BOQ delete removes DB row and media residuals."""

import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.boq.models import BOQ
from apps.boq.services.boq_job_progress import set_boq_job_progress
from apps.boq.services.extract_json_store import (
    boq_extract_dir,
    save_extract_json_for_boq,
)
from common.choices import BOQStatus, UserRole

User = get_user_model()


class BOQDeleteTests(TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="boq_delete_")
        self._media = Path(self._tmpdir)
        self._override = override_settings(MEDIA_ROOT=str(self._media))
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(lambda: shutil.rmtree(self._tmpdir, ignore_errors=True))

        self.owner = User.objects.create_user(
            email="owner@example.com", password="password", role=UserRole.EXPERT
        )
        self.other = User.objects.create_user(
            email="other@example.com", password="password", role=UserRole.EXPERT
        )
        self.client = Client()
        self.client.login(email="owner@example.com", password="password")

        workbook = SimpleUploadedFile(
            "delete_me.xlsx",
            b"PK\x03\x04fake-xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        make_list = SimpleUploadedFile(
            "delete_me_make.xlsx",
            b"PK\x03\x04fake-make",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.boq = BOQ.objects.create(
            user=self.owner,
            boq_name="Delete Target BOQ",
            status=BOQStatus.UPLOADED,
            uploaded_file=workbook,
            make_list_file=make_list,
            boq_data={"rows": []},
            make_list_data={"rows": []},
        )
        save_extract_json_for_boq(
            self.boq.boq_name,
            boq_data={"rows": []},
            make_list_data={"rows": []},
        )
        set_boq_job_progress(self.boq.pk, percent=12, label="testing", phase="test")

    def test_owner_delete_removes_row_and_residuals(self):
        extract_dir = boq_extract_dir(self.boq.boq_name)
        uploaded = Path(self.boq.uploaded_file.path)
        make_list = Path(self.boq.make_list_file.path)
        progress = self._media / "job_progress" / f"{self.boq.pk}.json"

        self.assertTrue(extract_dir.is_dir())
        self.assertTrue(uploaded.is_file())
        self.assertTrue(make_list.is_file())
        self.assertTrue(progress.is_file())

        url = reverse("boq:delete", args=[self.boq.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("boq:list"))

        self.assertFalse(BOQ.objects.filter(pk=self.boq.pk).exists())
        self.assertFalse(extract_dir.exists())
        self.assertFalse(uploaded.exists())
        self.assertFalse(make_list.exists())
        self.assertFalse(progress.exists())
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.owner,
                action="Deleted BOQ 'Delete Target BOQ'",
                entity="BOQ",
                entity_id="Delete Target BOQ",
            ).exists()
        )

    def test_list_shows_delete_control(self):
        response = self.client.get(reverse("boq:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("boq:delete", args=[self.boq.pk]))
        self.assertContains(response, "topbar-delete")
        self.assertContains(response, "topbar-view")

    def test_detail_hides_delete_control(self):
        response = self.client.get(reverse("boq:detail", args=[self.boq.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("boq:delete", args=[self.boq.pk]))

    def test_other_expert_cannot_delete(self):
        self.client.logout()
        self.client.login(email="other@example.com", password="password")
        response = self.client.post(reverse("boq:delete", args=[self.boq.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(BOQ.objects.filter(pk=self.boq.pk).exists())

    def test_admin_sees_expert_delete_in_audit(self):
        admin = User.objects.create_user(
            email="admin@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )
        self.owner.created_by = admin
        self.owner.save(update_fields=["created_by"])

        self.client.post(reverse("boq:delete", args=[self.boq.pk]))
        self.assertFalse(BOQ.objects.filter(pk=self.boq.pk).exists())

        self.client.logout()
        self.client.login(email="admin@example.com", password="password")
        response = self.client.get(reverse("audit:user_list", args=[self.owner.pk]))
        self.assertEqual(response.status_code, 200)
        logs = list(
            AuditLog.objects.filter(user=self.owner).values_list("action", "entity", "entity_id")
        )
        self.assertTrue(
            any(a.startswith("Deleted BOQ") for a, _, _ in logs),
            f"Expected Deleted BOQ audit for expert; got {logs!r}",
        )
        self.assertContains(response, "Deleted BOQ")
        self.assertContains(response, "Delete Target BOQ")

    def test_admin_delete_of_expert_boq_notes_owner_in_audit(self):
        admin = User.objects.create_user(
            email="admin2@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )
        self.owner.created_by = admin
        self.owner.save(update_fields=["created_by"])

        self.client.logout()
        self.client.login(email="admin2@example.com", password="password")
        self.client.post(reverse("boq:delete", args=[self.boq.pk]))

        self.assertTrue(
            AuditLog.objects.filter(
                user=admin,
                action="Deleted BOQ 'Delete Target BOQ' (owner: owner@example.com)",
                entity="BOQ",
                entity_id="Delete Target BOQ",
            ).exists()
        )
        response = self.client.get(reverse("audit:user_list", args=[admin.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "owner: owner@example.com")
