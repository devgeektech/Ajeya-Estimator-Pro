"""End-to-end workflow integration tests (Phase 11, Sprint 22).

Exercises the full pipeline with AI disabled (placeholder key): upload data ->
process run (match + cost + confidence) -> review -> approve -> export, plus the
failure path. These complement the per-service unit tests by validating that the
stages compose correctly and that status transitions, notifications and audit
entries all fire.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.costing.models import RateDetail
from apps.database_manager.models import DatabaseVersion, RateMaster
from apps.exports.services.export_service import ExportService
from apps.matching.models import ProductMatch
from apps.notifications.models import Notification
from apps.processing.models import ProcessingJob
from apps.review.services.review_service import ReviewService
from common.choices import BOQStatus, RunStatus
from common.exceptions import ProcessingError, ValidationError
from tasks.process_boq import process_boq_task
from workflows.boq_processing import process_boq_run


class _PipelineFixture(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="e2e@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.pipe = RateMaster.objects.create(
            database_version=self.version,
            tech_key="PIPE150",
            category="Pipe",
            sub_category="MS Pipe",
            size_mm=150,
            make="Jindal",
            supplier="ACME",
            net_material_rate=1000,
            final_amount_excl_gst=1000,
        )
        self.boq = BOQ.objects.create(
            user=self.user, boq_name="Tower A", uploaded_file="boq/x.xlsx"
        )
        self.run = BOQRun.objects.create(boq=self.boq, run_number=1)
        self.item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=10
        )


class ProcessPipelineTests(_PipelineFixture):
    def test_missing_run_is_skipped_without_error(self):
        missing_id = self.run.pk + 999

        with self.assertLogs("boq_ai", level="WARNING") as captured:
            result = process_boq_run(missing_id)

        self.assertIsNone(result)
        self.assertIn(f"run {missing_id} no longer exists", captured.output[0])

    def test_missing_run_task_is_skipped_without_error(self):
        missing_id = self.run.pk + 999

        with self.assertLogs("boq_ai", level="WARNING") as captured:
            result = process_boq_task.run(missing_id)

        self.assertIsNone(result)
        self.assertIn(f"run {missing_id} no longer exists", captured.output[0])

    @override_settings(OPENAI_API_KEY="placeholder-key")
    def test_full_pipeline_completes(self):
        process_boq_run(self.run.pk)

        self.run.refresh_from_db()
        self.boq.refresh_from_db()
        self.assertEqual(self.run.status, RunStatus.COMPLETED)
        self.assertEqual(self.boq.status, BOQStatus.UNDER_REVIEW)

        match = ProductMatch.objects.get(boq_item=self.item)
        self.assertEqual(match.product, self.pipe)
        self.assertEqual(match.match_reason, "exact")
        self.assertEqual(float(match.confidence_score), 100.0)

        self.assertTrue(RateDetail.objects.exists())

        job = ProcessingJob.objects.get(boq_run=self.run)
        self.assertEqual(job.progress, 100)
        self.assertEqual(job.status, RunStatus.COMPLETED)

        self.assertTrue(
            Notification.objects.filter(
                user=self.user, title="Processing complete"
            ).exists()
        )

    @override_settings(OPENAI_API_KEY="placeholder-key")
    def test_failure_path_marks_failed_and_notifies(self):
        with mock.patch(
            "apps.matching.services.matching_service.ProductMatchingService.match_run",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(ProcessingError):
                process_boq_run(self.run.pk)

        self.run.refresh_from_db()
        self.assertEqual(self.run.status, RunStatus.FAILED)
        job = ProcessingJob.objects.get(boq_run=self.run)
        self.assertEqual(job.status, RunStatus.FAILED)
        self.assertTrue(
            Notification.objects.filter(
                user=self.user, title="Processing failed"
            ).exists()
        )


class ReviewApproveExportTests(_PipelineFixture):
    @override_settings(OPENAI_API_KEY="placeholder-key")
    def test_process_review_approve_export(self):
        process_boq_run(self.run.pk)

        service = ReviewService()
        service.start_review(self.boq, self.user)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.UNDER_REVIEW)

        service.approve(self.boq, self.user)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.APPROVED)
        self.assertTrue(
            AuditLog.objects.filter(user=self.user, action="approve", entity="BOQ").exists()
        )

        export = ExportService().export_run(self.run, self.user)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.EXPORTED)
        self.assertTrue(export.internal_sheet)
        self.assertTrue(export.client_sheet)
        self.assertTrue(
            AuditLog.objects.filter(user=self.user, action="export", entity="BOQ").exists()
        )
        self.assertTrue(
            Notification.objects.filter(user=self.user, title="Export ready").exists()
        )

    @override_settings(OPENAI_API_KEY="placeholder-key")
    def test_cannot_export_before_approval(self):
        process_boq_run(self.run.pk)

        with self.assertRaises(ValidationError):
            ExportService().export_run(self.run, self.user)
