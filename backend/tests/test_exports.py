"""Tests for the export system (Sprint 19)."""
import io
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.costing.services.cost_service import CostCalculationService
from apps.database_manager.models import DatabaseVersion, RateMaster
from apps.exports.models import ExportFile
from apps.exports.services.export_service import ExportService
from apps.matching.models import ProductMatch
from common.choices import BOQStatus, RunStatus
from common.exceptions import ValidationError

_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA)
class ExportServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="ex@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.rate = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="APL", vendor="V1", purchase_rate=Decimal("800.00"),
        )
        self.boq = BOQ.objects.create(
            user=self.user, boq_name="B", uploaded_file="boq/x.xlsx", status=BOQStatus.APPROVED
        )
        self.run = BOQRun.objects.create(boq=self.boq, run_number=1, status=RunStatus.COMPLETED)
        self.item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal("3")
        )
        self.match = ProductMatch.objects.create(
            boq_item=self.item, product=self.rate, make="APL", vendor="V1",
            confidence_score=95, match_reason="exact",
        )
        CostCalculationService().calculate_item(self.match)

    def test_export_creates_files_and_marks_exported(self):
        export = ExportService().export_run(self.run, self.user)
        self.assertIsInstance(export, ExportFile)
        self.assertTrue(export.internal_sheet.name)
        self.assertTrue(export.client_sheet.name)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.EXPORTED)

    def test_internal_workbook_has_both_sheets(self):
        export = ExportService().export_run(self.run, self.user)
        wb = load_workbook(io.BytesIO(export.internal_sheet.read()))
        self.assertEqual(wb.sheetnames, ["Internal Review", "Client BOQ"])
        ws = wb["Internal Review"]
        self.assertEqual(ws["A1"].value, "#")
        self.assertEqual(ws["C2"].value, "PIPE150")  # product code row 1

    def test_client_standalone_has_computed_amount(self):
        export = ExportService().export_run(self.run, self.user)
        wb = load_workbook(io.BytesIO(export.client_sheet.read()))
        ws = wb["Client BOQ"]
        # Amount = final_rate * qty (computed, not a formula).
        final_rate = float(self.match.cost_breakdown.final_rate)
        self.assertAlmostEqual(ws["F2"].value, round(final_rate * 3, 2), places=2)

    def test_export_requires_approved(self):
        self.boq.status = BOQStatus.COMPLETED
        self.boq.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            ExportService().export_run(self.run, self.user)


@override_settings(MEDIA_ROOT=_MEDIA)
class ExportViewTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(email="o@x.com", password="x")
        self.other = get_user_model().objects.create_user(email="t@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.rate = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", purchase_rate=Decimal("800.00"),
        )
        self.boq = BOQ.objects.create(
            user=self.owner, boq_name="B", uploaded_file="boq/x.xlsx", status=BOQStatus.APPROVED
        )
        self.run = BOQRun.objects.create(boq=self.boq, run_number=1, status=RunStatus.COMPLETED)
        item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal("1")
        )
        match = ProductMatch.objects.create(
            boq_item=item, product=self.rate, confidence_score=95, match_reason="exact"
        )
        CostCalculationService().calculate_item(match)

    def test_owner_can_export(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("exports:generate", args=[self.boq.pk]))
        self.assertEqual(resp.status_code, 302)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.EXPORTED)
        self.assertTrue(ExportFile.objects.filter(boq_run=self.run).exists())

    def test_non_owner_cannot_export(self):
        self.client.force_login(self.other)
        resp = self.client.post(reverse("exports:generate", args=[self.boq.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(ExportFile.objects.exists())
