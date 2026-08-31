"""Tests for AI error message mapping."""
from django.test import SimpleTestCase

from ai.errors import (
    AI_CREDITS_EMPTY_MESSAGE,
    AI_RATE_LIMIT_MESSAGE,
    ANALYSIS_FAILED_DEFAULT_MESSAGE,
    format_ai_error_message,
    is_fatal_ai_limit_error,
    resolve_analysis_error_message,
)


class FormatAiErrorMessageTests(SimpleTestCase):
    def test_credit_balance_exhausted(self):
        raw = (
            "Error code: 429 - {'error': {'message': 'You have no credits remaining. "
            "Add credits…', 'code': 'credit_balance_exhausted'}}"
        )
        self.assertEqual(format_ai_error_message(raw), AI_CREDITS_EMPTY_MESSAGE)

    def test_insufficient_quota(self):
        self.assertEqual(
            format_ai_error_message("openai.RateLimitError: insufficient_quota"),
            AI_CREDITS_EMPTY_MESSAGE,
        )

    def test_idempotent_on_friendly_message(self):
        self.assertEqual(
            format_ai_error_message(AI_CREDITS_EMPTY_MESSAGE),
            AI_CREDITS_EMPTY_MESSAGE,
        )
        self.assertEqual(
            format_ai_error_message(f"AI request failed: {AI_CREDITS_EMPTY_MESSAGE}"),
            AI_CREDITS_EMPTY_MESSAGE,
        )

    def test_nested_import_wrapper_still_maps_credits(self):
        wrapped = (
            "Database import failed: Database import failed during embedding "
            f"generation: Embedding request failed: {AI_CREDITS_EMPTY_MESSAGE}"
        )
        self.assertEqual(format_ai_error_message(wrapped), AI_CREDITS_EMPTY_MESSAGE)

    def test_fatal_limit_detects_quota_and_rate_limit(self):
        self.assertTrue(is_fatal_ai_limit_error(AI_CREDITS_EMPTY_MESSAGE))
        self.assertTrue(is_fatal_ai_limit_error("insufficient_quota 429"))
        self.assertTrue(is_fatal_ai_limit_error(AI_RATE_LIMIT_MESSAGE))
        self.assertFalse(is_fatal_ai_limit_error("OPENAI_API_KEY is not configured."))

    def test_generic_rate_limit(self):
        self.assertEqual(
            format_ai_error_message("Rate limit exceeded (429)"),
            AI_RATE_LIMIT_MESSAGE,
        )

    def test_generic_analysis_failed_upgraded(self):
        self.assertEqual(
            format_ai_error_message("Analysis failed"),
            ANALYSIS_FAILED_DEFAULT_MESSAGE,
        )
        self.assertEqual(
            resolve_analysis_error_message(progress_label="Analysis failed"),
            ANALYSIS_FAILED_DEFAULT_MESSAGE,
        )
        self.assertEqual(
            resolve_analysis_error_message(
                last_error=AI_CREDITS_EMPTY_MESSAGE,
                progress_label="Analysis failed",
            ),
            AI_CREDITS_EMPTY_MESSAGE,
        )
