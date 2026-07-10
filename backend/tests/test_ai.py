"""Tests for the AI service (client mocked; no real API calls)."""

import json
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from ai.context import build_database_context, clear_database_context_cache
from ai.openai_client import get_client, is_configured
from ai.service import AIService
from apps.database_manager.models import DatabaseVersion, LabourConfig, LabourMaster, MaterialRate
from common.exceptions import AIServiceError


def _fake_client(content: str, usage=None):
    message = mock.Mock()
    message.content = content
    choice = mock.Mock()
    choice.message = message
    response = mock.Mock()
    response.choices = [choice]
    response.usage = usage
    client = mock.Mock()
    client.chat.completions.create.return_value = response
    return client


class IsConfiguredTests(SimpleTestCase):
    @override_settings(OPENAI_API_KEY="")
    def test_empty_key_disabled(self):
        self.assertFalse(is_configured())

    @override_settings(OPENAI_API_KEY="sk-REPLACE_WITH_YOUR_KEY")
    def test_placeholder_key_disabled(self):
        self.assertFalse(is_configured())
        self.assertFalse(AIService.is_enabled())

    @override_settings(OPENAI_API_KEY="sk-realLookingKey123")
    def test_real_key_enabled(self):
        self.assertTrue(is_configured())
        self.assertTrue(AIService.is_enabled())

    @override_settings(
        OPENAI_API_KEY="sk-realLookingKey123",
        OPENAI_TIMEOUT_SECONDS=120,
        OPENAI_MAX_RETRIES=1,
    )
    @mock.patch("ai.openai_client.OpenAI")
    def test_get_client_uses_timeout_and_retry_settings(self, openai_cls):
        get_client()

        self.assertEqual(openai_cls.call_args.kwargs["timeout"], 120.0)
        self.assertEqual(openai_cls.call_args.kwargs["max_retries"], 1)


@override_settings(OPENAI_API_KEY="sk-realLookingKey123", OPENAI_MODEL="gpt-5-mini")
class AIServiceTests(SimpleTestCase):
    def test_disabled_service_raises(self):
        with override_settings(OPENAI_API_KEY=""):
            with self.assertRaises(AIServiceError):
                AIService().complete("hello")

    @mock.patch("ai.service.get_client")
    def test_complete_returns_content(self, get_client):
        get_client.return_value = _fake_client("hello world")
        self.assertEqual(AIService().complete("hi"), "hello world")

    @mock.patch("ai.service.get_client")
    def test_gpt5_mini_omits_temperature(self, get_client):
        client = _fake_client("hello world")
        get_client.return_value = client

        AIService().complete("hi")

        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertNotIn("temperature", kwargs)

    @override_settings(OPENAI_MODEL="gpt-4o-mini")
    @mock.patch("ai.service.get_client")
    def test_older_models_keep_temperature_zero(self, get_client):
        client = _fake_client("hello world")
        get_client.return_value = client

        AIService().complete("hi")

        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0)

    @mock.patch("ai.service.get_client")
    def test_run_json_prompt_parses(self, get_client):
        get_client.return_value = _fake_client('{"schema": "boq_ai_extraction_v1"}')
        result = AIService().run_json_prompt(
            "test_json.txt",
            rows_json='[{"row_id":"1","description":"150 NB MS Pipe"}]',
            database_context="{}",
        )
        self.assertEqual(result["schema"], "boq_ai_extraction_v1")

    @mock.patch("ai.service.get_client")
    def test_invalid_json_raises(self, get_client):
        get_client.return_value = _fake_client("not json")
        with self.assertRaises(AIServiceError):
            AIService().run_json_prompt(
                "test_json.txt",
                rows_json='[{"row_id":"1","description":"x"}]',
                database_context="{}",
            )


class DatabaseContextCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_build_database_context_returns_unique_taxonomy_only(self):
        version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        MaterialRate.objects.create(
            database_version=version,
            tech_key="PIPE150",
            category="Pipe",
            sub_category="MS Pipe",
            size=150,
            make="Jindal",
        )
        MaterialRate.objects.create(
            database_version=version,
            tech_key="PIPE200",
            category="Pipe",
            sub_category="MS Pipe",
            size=200,
            make="Tata",
        )
        MaterialRate.objects.create(
            database_version=version,
            tech_key="VALVE80",
            category="Valve",
            sub_category="Butterfly Valve",
        )

        payload = json.loads(build_database_context())

        self.assertEqual(payload["categories"], ["Pipe", "Valve"])
        self.assertEqual(sorted(payload["sub_categories"]), ["Butterfly Valve", "MS Pipe"])
        self.assertNotIn("rate_master_vocabulary", payload)
        self.assertNotIn("Jindal", json.dumps(payload))

    def test_build_database_context_uses_tor_activities_not_tech_keys(self):
        version = DatabaseVersion.objects.create(
            version_number=2, is_active=True, source_filename="db.xlsx"
        )
        MaterialRate.objects.create(
            database_version=version,
            tech_key="PIPE150",
            category="Pipe",
            sub_category="MS Pipe",
        )
        LabourMaster.objects.create(
            database_version=version,
            tech_key="PIPE_MS_C_150",
            labour_type="SIZE_BASED",
        )
        LabourConfig.objects.create(database_version=version)

        clear_database_context_cache()
        payload = json.loads(build_database_context())

        self.assertEqual(payload["categories"], ["Pipe"])
        self.assertEqual(
            payload["activities"],
            ["testing", "scaffolding", "consumables", "painting"],
        )
        self.assertNotIn("PIPE_MS_C_150", payload["activities"])

    def test_clear_database_context_cache_rebuilds_active_version_context(self):
        version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        rate = MaterialRate.objects.create(
            database_version=version,
            tech_key="PIPE150",
            category="Pipe",
            sub_category="MS Pipe",
        )

        context = build_database_context()
        self.assertIn("Pipe", context)

        rate.tech_key = "VALVE150"
        rate.category = "Valve"
        rate.sub_category = "Butterfly Valve"
        rate.save(update_fields=["Tech_Key", "Category", "Sub_Category"])

        self.assertEqual(build_database_context(), context)

        clear_database_context_cache()
        rebuilt_context = build_database_context()

        self.assertIn("Valve", rebuilt_context)
        self.assertNotIn("Pipe", rebuilt_context)
