"""Tests for the processing queue (job lifecycle, progress, ownership)."""
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.processing.models import ProcessingJob
from apps.processing.services.job_service import ProcessingJobService
from common.choices import BOQStatus, RunStatus
from workflows.boq_processing import process_boq_run

User = get_user_model()


def make_boq(user, name="BOQ", with_item=True) -> BOQ:
    boq = BOQ.objects.create(
        user=user,
        boq_name=name,
        status=BOQStatus.UPLOADED,
        uploaded_file=SimpleUploadedFile(f"{name}.xlsx", b"dummy"),
    )
    run = BOQRun.objects.create(boq=boq, run_number=1, status=RunStatus.QUEUED)
    if with_item:
        BOQItem.objects.create(boq_run=run, row_number=1, description="Pipe", quantity=10, unit="m")
    return boq


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), OPENAI_API_KEY="placeholder-key")
class WorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("e@example.com", "pass12345")

    def test_process_run_completes_and_sets_statuses(self):
        boq = make_boq(self.user)
        run = boq.runs.get(run_number=1)
        process_boq_run(run.pk)
        run.refresh_from_db()
        boq.refresh_from_db()
        job = ProcessingJob.objects.get(boq_run=run)
        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(boq.status, BOQStatus.UNDER_REVIEW)
        self.assertEqual(job.status, RunStatus.COMPLETED)
        self.assertEqual(job.progress, 100)
        self.assertIsNotNone(run.started_at)
        self.assertIsNotNone(run.completed_at)


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    OPENAI_API_KEY="placeholder-key",
    CELERY_TASK_ALWAYS_EAGER=True,
)
class JobServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("e@example.com", "pass12345")

    def test_start_runs_to_completion_eagerly(self):
        boq = make_boq(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            ProcessingJobService(boq).start()
        boq.refresh_from_db()
        job = ProcessingJob.objects.get(boq_run__boq=boq)
        self.assertEqual(job.status, RunStatus.COMPLETED)
        self.assertEqual(job.progress, 100)
        self.assertEqual(boq.status, BOQStatus.UNDER_REVIEW)

    def test_reprocess_creates_new_run_and_clones_items(self):
        boq = make_boq(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            ProcessingJobService(boq).start()
        with self.captureOnCommitCallbacks(execute=True):
            ProcessingJobService(boq).start()
        self.assertEqual(boq.runs.count(), 2)
        new_run = boq.runs.order_by("-run_number").first()
        self.assertEqual(new_run.run_number, 2)
        self.assertEqual(new_run.items.count(), 1)


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    OPENAI_API_KEY="placeholder-key",
    CELERY_TASK_ALWAYS_EAGER=True,
)
class ProcessingViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin@example.com", "pass12345")
        self.alice = User.objects.create_user("alice@example.com", "pass12345")
        self.bob = User.objects.create_user("bob@example.com", "pass12345")
        self.boq = make_boq(self.alice, name="Alice")

    def test_owner_can_start_processing(self):
        self.client.force_login(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("processing:start", args=[self.boq.pk]))
        self.assertRedirects(response, reverse("boq:detail", args=[self.boq.pk]))
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.UNDER_REVIEW)

    def test_other_user_cannot_start_processing(self):
        self.client.force_login(self.bob)
        response = self.client.post(reverse("processing:start", args=[self.boq.pk]))
        self.assertEqual(response.status_code, 404)

    def test_status_endpoint_shows_progress_for_owner(self):
        run = self.boq.runs.get(run_number=1)
        process_boq_run(run.pk)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("processing:status", args=[run.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "100%")

    def test_status_endpoint_hidden_from_other_user(self):
        run = self.boq.runs.get(run_number=1)
        process_boq_run(run.pk)
        self.client.force_login(self.bob)
        response = self.client.get(reverse("processing:status", args=[run.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "100%")

    def test_processing_list_scoped_to_owner(self):
        run = self.boq.runs.get(run_number=1)
        process_boq_run(run.pk)
        self.client.force_login(self.bob)
        response = self.client.get(reverse("processing:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Alice")
