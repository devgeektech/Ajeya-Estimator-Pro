"""Tests for OpenAI TPM retry helpers."""
from django.test import SimpleTestCase

from ai.errors import AI_CREDITS_EMPTY_MESSAGE, AI_RATE_LIMIT_MESSAGE
from ai.retry import (
    call_with_openai_backoff,
    is_transient_openai_rate_limit,
    parse_openai_retry_seconds,
)
from common.exceptions import AIServiceError


class OpenAiRetryHelperTests(SimpleTestCase):
    def test_parse_retry_seconds_from_ms_and_s(self):
        raw = (
            "Rate limit reached for gpt-4o-mini on tokens per min (TPM): "
            "Limit 200000, Used 192340, Requested 8909. Please try again in 374ms."
        )
        self.assertAlmostEqual(parse_openai_retry_seconds(raw), 0.374)

        raw_s = "Please try again in 2.499s."
        self.assertAlmostEqual(parse_openai_retry_seconds(raw_s), 2.499)

    def test_transient_rate_limit_not_fatal_quota(self):
        tpm = (
            "openai.RateLimitError: tokens per min (TPM): Limit 200000. "
            "Please try again in 1.649s."
        )
        self.assertTrue(is_transient_openai_rate_limit(tpm))
        quota = "openai.RateLimitError: insufficient_quota"
        self.assertFalse(is_transient_openai_rate_limit(quota))

    def test_call_with_backoff_retries_transient_limit(self):
        attempts = {"count": 0}

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError(
                    "429 tokens per min (TPM): Please try again in 10ms."
                )
            return "ok"

        result = call_with_openai_backoff(flaky, operation_name="test")
        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 2)

    def test_call_with_backoff_stops_on_quota(self):
        def always_quota() -> str:
            raise RuntimeError("insufficient_quota 429")

        with self.assertRaises(AIServiceError) as ctx:
            call_with_openai_backoff(always_quota, operation_name="test")
        self.assertEqual(str(ctx.exception), AI_CREDITS_EMPTY_MESSAGE)

    def test_rate_limit_message_is_not_treated_as_transient_without_hint(self):
        self.assertFalse(is_transient_openai_rate_limit(AI_RATE_LIMIT_MESSAGE))
