"""BOQ Analyse dispatch and extract API error responses."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from apps.boq.models import BOQ
from apps.boq.services.boq_analysis_dispatch import AnalysisDispatchResult
from common.choices import BOQStatus, UserRole

User = get_user_model()


class BOQExtractDispatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="password", role=UserRole.EXPERT
        )
        self.boq = BOQ.objects.create(
            user=self.user,
            boq_name="Dispatch Target",
            status=BOQStatus.UPLOADED,
        )
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.client.login(email="owner@example.com", password="password")

    @patch("apps.boq.views.dispatch_boq_extraction")
    def test_extract_failed_response_keeps_dispatch_message(self, mock_dispatch):
        mock_dispatch.return_value = AnalysisDispatchResult(
            mode="failed",
            message="Redis is not running. Start Redis, then start the Celery worker.",
        )
        response = self.client.post(
            f"/boqs/{self.boq.pk}/extract/",
            {"ajax": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(
            payload["message"],
            "Redis is not running. Start Redis, then start the Celery worker.",
        )

    @override_settings(DEBUG=False, CELERY_SYNC_FALLBACK=True)
    @patch("apps.boq.services.boq_analysis_dispatch.broker_is_available", return_value=False)
    @patch("apps.boq.services.boq_analysis_dispatch.run_boq_extraction", return_value={})
    def test_sync_fallback_runs_when_redis_down(self, _runner, _broker):
        from apps.boq.services.boq_analysis_dispatch import dispatch_boq_extraction

        result = dispatch_boq_extraction(self.boq.pk)
        self.assertEqual(result.mode, "sync")
