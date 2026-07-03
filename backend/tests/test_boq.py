"""Tests for BOQ upload, parsing and ownership."""
import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.make_list.models import MakeListEntry
from common.choices import BOQStatus, RunStatus

from apps.boq.models import BOQ, BOQItem
from apps.boq.services.boq_service import BOQCreationService
from apps.boq.services.parser import parse_boq_items

User = get_user_model()


def build_boq_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["Description", "Quantity", "Unit"])
    ws.append(["150 NB MS Pipe", 100, "m"])
    ws.append(["Gate Valve 150mm", 4, "nos"])
    ws.append([None, None, None])  # blank row, must be skipped
    ws.append(["Sprinkler head", 250, "nos"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_make_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Makes"
    ws.append(["Make", "Category"])
    ws.append(["TATA", "Pipes"])
    ws.append(["Zoloto", "Valves"])
    ws.append(["TATA", "Pipes"])  # duplicate, deduped
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def boq_upload(name="boq.xlsx"):
    return SimpleUploadedFile(name, build_boq_workbook(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def make_upload(name="makes.xlsx"):
    return SimpleUploadedFile(name, build_make_workbook(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class ParserTests(TestCase):
    def test_parse_boq_items_skips_blank_and_numbers_rows(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_boq_workbook())
        tmp.close()
        items = parse_boq_items(tmp.name)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["row_number"], 1)
        self.assertEqual(items[0]["description"], "150 NB MS Pipe")
        self.assertEqual(str(items[0]["quantity"]), "100")
        self.assertEqual(items[2]["row_number"], 3)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BOQCreationServiceTests(TestCase):
    def setUp(self):
        self.expert = User.objects.create_user("expert@example.com", "pass12345")

    def test_creates_boq_run_items_and_makes(self):
        boq = BOQCreationService(
            user=self.expert,
            boq_name="Tower A",
            uploaded_file=boq_upload(),
            make_list_file=make_upload(),
        ).run()
        self.assertEqual(boq.status, BOQStatus.UPLOADED)
        self.assertEqual(boq.user, self.expert)
        run = boq.runs.get(run_number=1)
        self.assertEqual(run.status, RunStatus.QUEUED)
        self.assertEqual(BOQItem.objects.filter(boq_run=run).count(), 3)
        self.assertEqual(MakeListEntry.objects.filter(boq_run=run).count(), 2)

    def test_make_list_optional(self):
        boq = BOQCreationService(
            user=self.expert, boq_name="No Makes", uploaded_file=boq_upload()
        ).run()
        run = boq.runs.get(run_number=1)
        self.assertEqual(BOQItem.objects.filter(boq_run=run).count(), 3)
        self.assertEqual(MakeListEntry.objects.filter(boq_run=run).count(), 0)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BOQOwnershipTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin@example.com", "pass12345")
        self.alice = User.objects.create_user("alice@example.com", "pass12345")
        self.bob = User.objects.create_user("bob@example.com", "pass12345")
        self.alice_boq = BOQCreationService(self.alice, "Alice BOQ", boq_upload()).run()

    def test_expert_sees_only_own_boqs(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("boq:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Alice BOQ")

    def test_owner_sees_own_boq(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("boq:list"))
        self.assertContains(response, "Alice BOQ")

    def test_other_expert_cannot_open_boq(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("boq:detail", args=[self.alice_boq.pk]))
        self.assertEqual(response.status_code, 404)

    def test_super_admin_can_open_any_boq(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("boq:detail", args=[self.alice_boq.pk]))
        self.assertEqual(response.status_code, 200)

    def test_upload_view_creates_boq(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("boq:upload"),
            {"boq_name": "Bob BOQ", "uploaded_file": boq_upload(), "make_list_file": make_upload()},
        )
        boq = BOQ.objects.get(boq_name="Bob BOQ")
        self.assertRedirects(response, reverse("boq:detail", args=[boq.pk]))
        self.assertEqual(boq.user, self.bob)
