"""Tests for the AI service (client mocked; no real API calls)."""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from ai.extractors.activity_extractor import extract_activities
from ai.extractors.analyzer import analyze_run
from ai.extractors.product_extractor import extract_product
from ai.openai_client import is_configured
from ai.service import AIService
from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.matching.models import ActivityMatch
from common.exceptions import AIServiceError


def _fake_client(content: str):
    """Build a mock OpenAI client whose completion returns ``content``."""
    message = mock.Mock()
    message.content = content
    choice = mock.Mock()
    choice.message = message
    response = mock.Mock()
    response.choices = [choice]
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


@override_settings(OPENAI_API_KEY="sk-realLookingKey123", OPENAI_MODEL="gpt-4o-mini")
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
    def test_complete_logs_runtime_instruction(self, get_client):
        get_client.return_value = _fake_client("hello world")

        with self.assertLogs("boq_ai.ai_instructions", level="INFO") as captured:
            AIService().complete("visible instruction")

        payload = json.loads(captured.output[0].split("INFO:boq_ai.ai_instructions:", 1)[1])
        self.assertEqual(payload["event"], "ai_runtime_instruction")
        self.assertEqual(payload["model"], "gpt-4o-mini")
        self.assertEqual(payload["template_name"], "")
        self.assertFalse(payload["json_mode"])
        self.assertEqual(payload["instruction_text"], "visible instruction")

    @mock.patch("ai.service.get_client")
    def test_run_json_prompt_parses(self, get_client):
        get_client.return_value = _fake_client('{"product": "Pipe", "size": "150 NB"}')
        result = AIService().run_json_prompt(
            "product_extraction.txt",
            description="150 NB MS Pipe",
            row_json='{"description":"150 NB MS Pipe"}',
            database_context="{}",
        )
        self.assertEqual(result["product"], "Pipe")

    @mock.patch("ai.service.get_client")
    def test_run_json_prompt_logs_rendered_template_instruction(self, get_client):
        get_client.return_value = _fake_client('{"product": "Pipe"}')

        with self.assertLogs("boq_ai.ai_instructions", level="INFO") as captured:
            AIService().run_json_prompt(
                "product_extraction.txt",
                description="150 NB MS Pipe",
                row_json='{"description":"150 NB MS Pipe"}',
                database_context='{"products":[]}',
            )

        payload = json.loads(captured.output[0].split("INFO:boq_ai.ai_instructions:", 1)[1])
        self.assertEqual(payload["event"], "ai_runtime_instruction")
        self.assertEqual(payload["template_name"], "product_extraction.txt")
        self.assertTrue(payload["json_mode"])
        self.assertIn("150 NB MS Pipe", payload["instruction_text"])
        self.assertIn('{"products":[]}', payload["instruction_text"])

    @mock.patch("ai.service.get_client")
    def test_invalid_json_raises(self, get_client):
        get_client.return_value = _fake_client("not json")
        with self.assertRaises(AIServiceError):
            AIService().run_json_prompt(
                "product_extraction.txt",
                description="x",
                row_json='{"description":"x"}',
                database_context="{}",
            )

    @mock.patch("ai.service.get_client")
    def test_provider_error_is_wrapped(self, get_client):
        client = mock.Mock()
        client.chat.completions.create.side_effect = RuntimeError("boom")
        get_client.return_value = client
        with self.assertRaises(AIServiceError):
            AIService().complete("hi")

    def test_missing_prompt_variable_raises(self):
        with self.assertRaises(AIServiceError):
            AIService().run_prompt("validation.txt")  # missing description/candidate


@override_settings(OPENAI_API_KEY="sk-realLookingKey123", OPENAI_MODEL="gpt-4o-mini")
class ProductExtractorTests(SimpleTestCase):
    @mock.patch("ai.service.get_client")
    def test_extract_product_returns_fields(self, get_client):
        payload = {"product": "Pipe", "size": "150 NB", "material": "MS", "make": "Jindal"}
        get_client.return_value = _fake_client(json.dumps(payload))
        result = extract_product("150 NB MS Pipe Jindal")
        self.assertEqual(result, payload | {"products": []})

    @mock.patch("ai.service.get_client")
    def test_extract_product_fills_missing_fields(self, get_client):
        get_client.return_value = _fake_client('{"product": "Valve"}')
        result = extract_product("Gate valve")
        self.assertEqual(result["product"], "Valve")
        self.assertIsNone(result["size"])
        self.assertIsNone(result["make"])
        self.assertEqual(result["products"], [])

    @mock.patch("ai.service.get_client")
    def test_extract_product_preserves_product_candidates(self, get_client):
        payload = {
            "products": [
                {
                    "product": "MS Pipe",
                    "size": "150 NB",
                    "material": "MS",
                    "make": None,
                    "category": "Pipe",
                    "subcategory": "MS Pipe",
                    "database_hint": "PIPE150",
                }
            ]
        }
        get_client.return_value = _fake_client(json.dumps(payload))
        result = extract_product("Supply and install 150 NB MS Pipe")
        self.assertEqual(result["product"], "MS Pipe")
        self.assertEqual(result["products"][0]["database_hint"], "PIPE150")


@override_settings(OPENAI_API_KEY="sk-realLookingKey123", OPENAI_MODEL="gpt-4o-mini")
class ActivityExtractorTests(SimpleTestCase):
    @mock.patch("ai.service.get_client")
    def test_extract_activities_filters_to_allowed(self, get_client):
        get_client.return_value = _fake_client(
            '{"activities": ["Excavation", "installation", "dancing"]}'
        )
        result = extract_activities("Lay and install pipe in trench")
        self.assertEqual(result, ["excavation", "installation"])

    @mock.patch("ai.service.get_client")
    def test_extract_activities_handles_missing_key(self, get_client):
        get_client.return_value = _fake_client('{"foo": "bar"}')
        self.assertEqual(extract_activities("anything"), [])


@override_settings(OPENAI_API_KEY="sk-realLookingKey123", OPENAI_MODEL="gpt-4o-mini")
class AnalyzeRunTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(  # type: ignore[attr-defined]
            email="exp@example.com", password="x"
        )
        boq = BOQ.objects.create(user=user, boq_name="Test", uploaded_file="boq/x.xlsx")  # type: ignore[attr-defined]
        self.run = BOQRun.objects.create(boq=boq, run_number=1)  # type: ignore[attr-defined]
        BOQItem.objects.create(boq_run=self.run, row_number=1, description="150 NB MS pipe")  # type: ignore[attr-defined]
        BOQItem.objects.create(boq_run=self.run, row_number=2, description="Excavate trench")  # type: ignore[attr-defined]

    @mock.patch("ai.extractors.analyzer.extract_activities")
    @mock.patch("ai.extractors.analyzer.extract_product")
    def test_analyze_run_persists_results(self, extract_product_mock, extract_activities_mock):
        extract_product_mock.return_value = {
            "product": "Pipe", "size": "150 NB", "material": "MS", "make": None,
        }
        extract_activities_mock.return_value = ["excavation"]

        analyzed = analyze_run(self.run)

        self.assertEqual(analyzed, 2)
        items = list(self.run.items.all())  # type: ignore[attr-defined]
        self.assertEqual(items[0].ai_extraction["product"], "Pipe")
        self.assertEqual(ActivityMatch.objects.filter(boq_item=items[0]).count(), 1)  # type: ignore[attr-defined]

    @mock.patch("ai.extractors.analyzer.extract_activities")
    @mock.patch("ai.extractors.analyzer.extract_product")
    def test_analyze_run_logs_each_row_extraction(self, extract_product_mock, extract_activities_mock):
        extract_product_mock.return_value = {
            "product": "Pipe", "size": "150 NB", "material": "MS", "make": None,
        }
        extract_activities_mock.return_value = ["installation"]

        with self.assertLogs("boq_ai.ai_rows", level="INFO") as captured:
            analyze_run(self.run)

        extraction_lines = [
            line for line in captured.output if '"event": "ai_row_extraction"' in line
        ]
        self.assertEqual(len(extraction_lines), 2)
        payload = json.loads(extraction_lines[0].split("INFO:boq_ai.ai_rows:", 1)[1])
        self.assertEqual(payload["excel_row_number"], 1)
        self.assertEqual(payload["description"], "150 NB MS pipe")
        self.assertEqual(payload["product_extraction"]["product"], "Pipe")
        self.assertEqual(payload["activities"], ["installation"])
        self.assertIn("row_json", payload)
        self.assertIn("fetched_row_json", payload)
        self.assertEqual(payload["ai_output_json"]["product_extraction"]["product"], "Pipe")
        self.assertEqual(payload["ai_output_json"]["activities"], ["installation"])

    @mock.patch("ai.extractors.analyzer.extract_product")
    def test_analyze_run_skips_failing_item(self, extract_product_mock):
        extract_product_mock.side_effect = AIServiceError("boom")
        analyzed = analyze_run(self.run)
        self.assertEqual(analyzed, 0)

    @mock.patch("ai.extractors.analyzer.extract_product")
    def test_analyze_run_logs_row_failures(self, extract_product_mock):
        extract_product_mock.side_effect = AIServiceError("boom")

        with self.assertLogs("boq_ai.ai_rows", level="ERROR") as captured:
            analyze_run(self.run)

        failure_lines = [
            line for line in captured.output if '"event": "ai_row_extraction_failed"' in line
        ]
        self.assertEqual(len(failure_lines), 2)
        payload = json.loads(failure_lines[0].split("ERROR:boq_ai.ai_rows:", 1)[1])
        self.assertEqual(payload["excel_row_number"], 1)
        self.assertEqual(payload["error"], "boom")
        self.assertIn("row_json", payload)
        self.assertIn("fetched_row_json", payload)

    @mock.patch("ai.extractors.analyzer.extract_activities")
    @mock.patch("ai.extractors.analyzer.extract_product")
    def test_analyze_run_is_idempotent(self, extract_product_mock, extract_activities_mock):
        extract_product_mock.return_value = {"product": "Pipe", "size": None, "material": None, "make": None}
        extract_activities_mock.return_value = ["excavation", "installation"]

        analyze_run(self.run)
        analyze_run(self.run)

        # Re-running must not duplicate activity matches.
        self.assertEqual(ActivityMatch.objects.count(), 4)  # type: ignore[attr-defined]
