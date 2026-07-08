"""Tests for the AI service (client mocked; no real API calls)."""

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from ai.context import build_database_context, clear_database_context_cache
from ai.extractors.analyzer import analyze_run
from ai.extractors.row_extractor import extract_boq_row, extract_boq_rows
from ai.openai_client import get_client, is_configured
from ai.service import AIService
from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.database_manager.models import DatabaseVersion, LabourMaster, RateMaster
from apps.matching.models import ActivityMatch
from common.exceptions import AIServiceError


def _fake_client(content: str, usage=None):
    """Build a mock OpenAI client whose completion returns ``content``."""
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
    def test_complete_logs_runtime_instruction(self, get_client):
        get_client.return_value = _fake_client("hello world")

        with self.assertLogs("boq_ai.ai_instructions", level="INFO") as captured:
            AIService().complete("visible instruction")

        payload = json.loads(
            captured.output[0].split("INFO:boq_ai.ai_instructions:", 1)[1]
        )
        self.assertEqual(payload["event"], "ai_runtime_instruction")
        self.assertEqual(payload["model"], "gpt-5-mini")
        self.assertEqual(payload["template_name"], "")
        self.assertFalse(payload["json_mode"])
        self.assertEqual(payload["instruction_text"], "visible instruction")

    @mock.patch("ai.service.get_client")
    def test_complete_logs_cached_token_usage(self, get_client):
        get_client.return_value = _fake_client(
            "hello world",
            usage={
                "prompt_tokens": 1200,
                "completion_tokens": 20,
                "total_tokens": 1220,
                "prompt_tokens_details": {"cached_tokens": 1024},
            },
        )

        with self.assertLogs("boq_ai.ai_instructions", level="INFO") as captured:
            AIService().complete("visible instruction", template_name="x.txt")

        usage_lines = [
            line for line in captured.output if '"event": "ai_token_usage"' in line
        ]
        self.assertEqual(len(usage_lines), 1)
        payload = json.loads(usage_lines[0].split("INFO:boq_ai.ai_instructions:", 1)[1])
        self.assertEqual(payload["template_name"], "x.txt")
        self.assertEqual(payload["prompt_tokens"], 1200)
        self.assertEqual(payload["cached_tokens"], 1024)

    @mock.patch("ai.service.get_client")
    def test_run_json_prompt_parses(self, get_client):
        get_client.return_value = _fake_client('{"schema": "boq_ai_extraction_v1"}')
        result = AIService().run_json_prompt(
            "boq_row_extraction.txt",
            description="150 NB MS Pipe",
            row_json='{"description":"150 NB MS Pipe"}',
            database_context="{}",
        )
        self.assertEqual(result["schema"], "boq_ai_extraction_v1")

    @mock.patch("ai.service.get_client")
    def test_run_json_prompt_logs_rendered_template_instruction(self, get_client):
        get_client.return_value = _fake_client('{"product": "Pipe"}')

        with self.assertLogs("boq_ai.ai_instructions", level="INFO") as captured:
            AIService().run_json_prompt(
                "boq_row_extraction.txt",
                description="150 NB MS Pipe",
                row_json='{"description":"150 NB MS Pipe"}',
                database_context='{"rate_master_vocabulary":[]}',
            )

        payload = json.loads(
            captured.output[0].split("INFO:boq_ai.ai_instructions:", 1)[1]
        )
        self.assertEqual(payload["event"], "ai_runtime_instruction")
        self.assertEqual(payload["template_name"], "boq_row_extraction.txt")
        self.assertTrue(payload["json_mode"])
        self.assertIn("150 NB MS Pipe", payload["instruction_text"])
        self.assertIn('{"rate_master_vocabulary":[]}', payload["instruction_text"])

    @mock.patch("ai.service.get_client")
    def test_invalid_json_raises(self, get_client):
        get_client.return_value = _fake_client("not json")
        with self.assertRaises(AIServiceError):
            AIService().run_json_prompt(
                "boq_row_extraction.txt",
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


@override_settings(OPENAI_API_KEY="sk-realLookingKey123", OPENAI_MODEL="gpt-5-mini")
class RowExtractorTests(SimpleTestCase):
    @mock.patch("ai.service.get_client")
    def test_extract_boq_row_returns_products_and_activities(self, get_client):
        payload = {
            "database_products": [
                {
                    "category": "Pipe",
                    "sub_category": "MS Pipe",
                    "class": "MS",
                    "size_mm": "150 NB",
                    "make": "Jindal",
                }
            ],
            "activities": ["installation", "dancing"],
        }
        get_client.return_value = _fake_client(json.dumps(payload))
        result = extract_boq_row(
            "150 NB MS Pipe Jindal",
            database_context='{"activities":["installation"]}',
        )
        self.assertEqual(result["schema"], "boq_ai_extraction_v1")
        self.assertEqual(result["database_products"][0]["category"], "Pipe")
        self.assertEqual(result["database_products"][0]["size_mm"], "150 NB")
        self.assertEqual(result["activities"], ["installation"])

    @mock.patch("ai.service.get_client")
    def test_extract_boq_row_fills_missing_fields(self, get_client):
        get_client.return_value = _fake_client('{"category": "Valve"}')
        result = extract_boq_row("Gate valve")
        self.assertEqual(result["database_products"][0]["category"], "Valve")
        self.assertIsNone(result["database_products"][0]["size_mm"])
        self.assertIsNone(result["database_products"][0]["make"])

    @mock.patch("ai.service.get_client")
    def test_extract_boq_row_preserves_product_candidates(self, get_client):
        payload = {
            "database_products": [
                {
                    "product": "MS Pipe",
                    "size": "150 NB",
                    "material": "MS",
                    "make": None,
                    "category": "Pipe",
                    "sub_category": "MS Pipe",
                }
            ]
        }
        get_client.return_value = _fake_client(json.dumps(payload))
        result = extract_boq_row("Supply and install 150 NB MS Pipe")
        self.assertEqual(result["database_products"][0]["category"], "Pipe")
        self.assertEqual(result["database_products"][0]["sub_category"], "MS Pipe")
        self.assertEqual(result["database_products"][0]["size_mm"], "150 NB")

    @mock.patch("ai.service.get_client")
    def test_extract_boq_row_preserves_multiple_products_and_activity(self, get_client):
        payload = {
            "database_products": [
                {"category": "Pipe", "sub_category": "MS Pipe", "size_mm": "150 NB"},
                {
                    "category": "Valve",
                    "sub_category": "Butterfly Valve",
                    "size_mm": "80 MM",
                },
            ],
            "activities": ["installation"],
        }
        get_client.return_value = _fake_client(json.dumps(payload))

        result = extract_boq_row(
            "Supply and install 150 NB MS pipe with 80 MM butterfly valve",
            database_context='{"activities":["installation"]}',
        )

        self.assertEqual(len(result["database_products"]), 2)
        self.assertEqual(result["database_products"][0]["sub_category"], "MS Pipe")
        self.assertEqual(result["database_products"][1]["sub_category"], "Butterfly Valve")
        self.assertEqual(result["activities"], ["installation"])

    @mock.patch("ai.service.get_client")
    def test_extract_boq_row_deduplicates_products(self, get_client):
        payload = {
            "database_products": [
                {"product": "MS Pipe", "sub_category": "MS Pipe", "size_mm": "150 NB"},
                {
                    "product_name": "MS Pipe",
                    "sub_category": "MS Pipe",
                    "size_mm": "150 NB",
                },
                {"product_name": "Butterfly Valve", "size_mm": "80 MM"},
            ]
        }
        get_client.return_value = _fake_client(json.dumps(payload))

        result = extract_boq_row("Supply MS Pipe and butterfly valve")

        self.assertEqual(len(result["database_products"]), 2)
        self.assertEqual(result["database_products"][0]["product_name"], "MS Pipe")
        self.assertEqual(result["database_products"][1]["product_name"], "Butterfly Valve")

    @mock.patch("ai.service.get_client")
    def test_extract_boq_rows_returns_results_by_row_id(self, get_client):
        payload = {
            "schema": "boq_ai_batch_extraction_v1",
            "rows": [
                {
                    "row_id": "10",
                    "extraction": {
                        "database_products": [{"product": "MS Pipe", "size": "150 NB"}],
                        "activities": ["installation"],
                    },
                },
                {
                    "row_id": "11",
                    "extraction": {"database_products": [], "activities": ["dancing"]},
                },
            ],
        }
        get_client.return_value = _fake_client(json.dumps(payload))

        result = extract_boq_rows(
            [
                {"row_id": "10", "description": "150 NB MS Pipe", "row_json": {}},
                {"row_id": "11", "description": "Heading", "row_json": {}},
            ],
            database_context='{"activities":["installation"]}',
        )

        self.assertEqual(result["10"]["database_products"][0]["product_name"], "MS Pipe")
        self.assertEqual(result["10"]["database_products"][0]["size_mm"], "150 NB")
        self.assertEqual(result["10"]["activities"], ["installation"])
        self.assertEqual(result["11"]["database_products"], [])
        self.assertEqual(result["11"]["activities"], [])

    @mock.patch("ai.service.get_client")
    def test_extract_boq_rows_preserves_all_row_products_and_activities(
        self, get_client
    ):
        payload = {
            "schema": "boq_ai_batch_extraction_v1",
            "rows": [
                {
                    "row_id": "10",
                    "extraction": {
                        "database_products": [
                            {"product_name": "MS Pipe", "size_mm": "150 NB"},
                            {"product_name": "Butterfly Valve", "size_mm": "80 MM"},
                        ],
                        "activities": ["installation", "testing"],
                    },
                },
                {
                    "row_id": "11",
                    "extraction": {
                        "database_products": [
                            {"product_name": "Jockey Pump", "capacity": "180 LPM"}
                        ],
                        "activities": ["installation"],
                    },
                },
            ],
        }
        get_client.return_value = _fake_client(json.dumps(payload))

        result = extract_boq_rows(
            [
                {"row_id": "10", "description": "Pipe with valve", "row_json": {}},
                {"row_id": "11", "description": "Jockey pump", "row_json": {}},
            ],
            database_context='{"activities":["installation","testing"]}',
        )

        self.assertEqual(len(result["10"]["database_products"]), 2)
        self.assertEqual(result["10"]["activities"], ["installation", "testing"])
        self.assertEqual(result["11"]["database_products"][0]["product_name"], "Jockey Pump")
        self.assertEqual(result["11"]["activities"], ["installation"])


class DatabaseContextCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_build_database_context_reuses_cached_vocabulary(self):
        version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        RateMaster.objects.create(
            database_version=version,
            tech_key="PIPE150",
            category="Pipe",
            sub_category="MS Pipe",
            size_mm=150,
            make="Jindal",
            supplier="ACME",
        )
        LabourMaster.objects.create(
            database_version=version,
            tech_key="PIPE150_INSTALL",
            labour_type="installation",
        )

        context = build_database_context()
        self.assertIn("Pipe", context)
        self.assertIn("installation", context)

        with self.assertNumQueries(1):
            cached_context = build_database_context()

        self.assertEqual(cached_context, context)

    def test_clear_database_context_cache_rebuilds_active_version_context(self):
        version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        rate = RateMaster.objects.create(
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
        rate.save(update_fields=["tech_key", "category", "sub_category"])

        self.assertEqual(build_database_context(), context)

        clear_database_context_cache()
        rebuilt_context = build_database_context()

        self.assertIn("Valve", rebuilt_context)
        self.assertNotIn("Pipe", rebuilt_context)

    def test_database_context_rebuilds_when_active_version_changes(self):
        first = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db-v1.xlsx"
        )
        second = DatabaseVersion.objects.create(
            version_number=2, is_active=False, source_filename="db-v2.xlsx"
        )
        third = DatabaseVersion.objects.create(
            version_number=3, is_active=False, source_filename="db-v3.xlsx"
        )
        RateMaster.objects.create(
            database_version=first,
            tech_key="PIPE150",
            category="Pipe",
        )
        RateMaster.objects.create(
            database_version=second,
            tech_key="PUMP01",
            category="Pump",
        )
        RateMaster.objects.create(
            database_version=third,
            tech_key="VALVE01",
            category="Valve",
        )

        self.assertIn("Pipe", build_database_context())

        first.is_active = False
        first.save(update_fields=["is_active"])
        third.is_active = True
        third.save(update_fields=["is_active"])
        clear_database_context_cache()

        third_context = build_database_context()
        self.assertIn("Valve", third_context)
        self.assertNotIn("Pipe", third_context)

        third.is_active = False
        third.save(update_fields=["is_active"])
        second.is_active = True
        second.save(update_fields=["is_active"])
        clear_database_context_cache()

        second_context = build_database_context()
        self.assertIn("Pump", second_context)
        self.assertNotIn("Valve", second_context)


@override_settings(OPENAI_API_KEY="sk-realLookingKey123", OPENAI_MODEL="gpt-5-mini")
class AnalyzeRunTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(  # type: ignore[attr-defined]
            email="exp@example.com", password="x"
        )
        boq = BOQ.objects.create(user=user, boq_name="Test", uploaded_file="boq/x.xlsx")  # type: ignore[attr-defined]
        self.run = BOQRun.objects.create(boq=boq, run_number=1)  # type: ignore[attr-defined]
        BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS pipe"
        )  # type: ignore[attr-defined]
        BOQItem.objects.create(
            boq_run=self.run, row_number=2, description="Excavate trench"
        )  # type: ignore[attr-defined]

    @mock.patch("ai.extractors.analyzer.extract_boq_rows")
    def test_analyze_run_persists_results(self, extract_boq_rows_mock):
        items = list(self.run.items.all())  # type: ignore[attr-defined]
        extract_boq_rows_mock.return_value = {
            str(item.pk): {
                "schema": "boq_ai_extraction_v1",
                "database_products": [{"category": "Pipe", "size_mm": "150 NB", "make": None}],
                "activities": ["excavation"],
            }
            for item in items
        }

        analyzed = analyze_run(self.run)

        self.assertEqual(analyzed, 2)
        items = list(self.run.items.all())  # type: ignore[attr-defined]
        self.assertEqual(items[0].ai_extraction["database_products"][0]["category"], "Pipe")
        self.assertEqual(ActivityMatch.objects.filter(boq_item=items[0]).count(), 1)  # type: ignore[attr-defined]

    @mock.patch("ai.extractors.analyzer.extract_boq_rows")
    def test_analyze_run_passes_traversable_source_row_when_row_json_missing(
        self, extract_boq_rows_mock
    ):
        extract_boq_rows_mock.return_value = {}

        analyze_run(self.run)

        batch_rows = extract_boq_rows_mock.call_args_list[0].args[0]
        source_row = batch_rows[0]["row_json"]
        self.assertEqual(source_row["schema"], "boq_row_group_v1")
        self.assertIsInstance(source_row["rows"], list)
        self.assertEqual(source_row["rows"][0]["description"], "150 NB MS pipe")
        self.assertEqual(source_row["description"], "150 NB MS pipe")
        self.assertEqual(source_row["unit"], "")
        self.assertEqual(source_row["quantity"], 0)
        self.assertEqual(source_row["primary_excel_row_number"], 1)
        self.assertEqual(extract_boq_rows_mock.call_count, 1)

    @mock.patch("ai.extractors.analyzer.extract_boq_rows")
    def test_analyze_run_preserves_grouped_source_row_description_and_parameters(
        self, extract_boq_rows_mock
    ):
        item = self.run.items.first()
        item.description = "Pipes and fittings\n150 NB MS pipe"
        item.unit = "m"
        item.quantity = 25
        item.original_data = {
            "s_no": "1.1",
            "description": "150 NB MS pipe",
            "unit": "m",
            "quantity": "25",
        }
        item.row_json = {
            "schema": "boq_row_group_v1",
            "primary_excel_row_number": 4,
            "excel_row_numbers": [3, 4],
            "serial_number": "1.1",
            "description": "Pipes and fittings\n150 NB MS pipe",
            "unit": "m",
            "quantity": "25",
            "rows": [
                {
                    "excel_row_number": 3,
                    "serial_number": "1",
                    "description": "Pipes and fittings",
                    "unit": "",
                    "quantity": None,
                    "canonical": {
                        "s_no": "1",
                        "description": "Pipes and fittings",
                        "unit": "",
                        "quantity": None,
                    },
                },
                {
                    "excel_row_number": 4,
                    "serial_number": "1.1",
                    "description": "150 NB MS pipe",
                    "unit": "m",
                    "quantity": "25",
                    "canonical": {
                        "s_no": "1.1",
                        "description": "150 NB MS pipe",
                        "unit": "m",
                        "quantity": "25",
                    },
                },
            ],
        }
        item.save(
            update_fields=[
                "description",
                "unit",
                "quantity",
                "original_data",
                "row_json",
            ]
        )
        extract_boq_rows_mock.return_value = {}

        analyze_run(self.run)

        batch_rows = extract_boq_rows_mock.call_args_list[0].args[0]
        source_row = next(
            row["row_json"] for row in batch_rows if row["row_id"] == str(item.pk)
        )
        self.assertEqual(
            source_row["description"], "Pipes and fittings\n150 NB MS pipe"
        )
        self.assertEqual(source_row["serial_number"], "1.1")
        self.assertEqual(source_row["unit"], "m")
        self.assertEqual(source_row["quantity"], "25")
        self.assertEqual(source_row["rows"][1]["canonical"]["s_no"], "1.1")

    @mock.patch("ai.extractors.analyzer.extract_boq_rows")
    def test_analyze_run_logs_each_row_extraction(self, extract_boq_rows_mock):
        items = list(self.run.items.all())  # type: ignore[attr-defined]
        extract_boq_rows_mock.return_value = {
            str(item.pk): {
                "schema": "boq_ai_extraction_v1",
                "database_products": [{"category": "Pipe", "size_mm": "150 NB", "make": None}],
                "activities": ["installation"],
            }
            for item in items
        }

        with self.assertLogs("boq_ai.ai_rows", level="INFO") as captured:
            analyze_run(self.run)

        extraction_lines = [
            line for line in captured.output if '"event": "ai_row_extraction"' in line
        ]
        self.assertEqual(len(extraction_lines), 2)
        payload = json.loads(extraction_lines[0].split("INFO:boq_ai.ai_rows:", 1)[1])
        self.assertEqual(payload["excel_row_number"], 1)
        self.assertIn("source_row", payload)
        self.assertEqual(payload["source_row"]["description"], "150 NB MS pipe")
        self.assertEqual(payload["source_row"]["quantity"], 0)
        self.assertEqual(payload["extraction"]["database_products"][0]["category"], "Pipe")
        self.assertEqual(payload["extraction"]["activities"], ["installation"])

    @mock.patch("ai.extractors.analyzer.extract_boq_rows")
    def test_analyze_run_skips_failing_item(self, extract_boq_rows_mock):
        extract_boq_rows_mock.side_effect = AIServiceError("boom")
        analyzed = analyze_run(self.run)
        self.assertEqual(analyzed, 0)

    @override_settings(AI_ROW_EXTRACTION_BATCH_SIZE=2)
    @mock.patch("ai.extractors.analyzer.extract_boq_rows")
    def test_analyze_run_splits_failed_batch_and_retries_rows(
        self, extract_boq_rows_mock
    ):
        call_sizes = []

        def results(rows, *args, **kwargs):
            call_sizes.append(len(rows))
            if len(rows) > 1:
                raise AIServiceError("Request timed out.")
            return {
                str(row["row_id"]): {
                    "schema": "boq_ai_extraction_v1",
                    "database_products": [{"category": "Pipe"}],
                    "activities": ["installation"],
                }
                for row in rows
            }

        extract_boq_rows_mock.side_effect = results

        analyzed = analyze_run(self.run)

        self.assertEqual(analyzed, 2)
        self.assertEqual(call_sizes, [2, 1, 1])
        self.assertEqual(ActivityMatch.objects.count(), 2)  # type: ignore[attr-defined]

    @mock.patch("ai.extractors.analyzer.extract_boq_rows")
    def test_analyze_run_logs_row_failures(self, extract_boq_rows_mock):
        extract_boq_rows_mock.side_effect = AIServiceError("boom")

        with self.assertLogs("boq_ai.ai_rows", level="ERROR") as captured:
            analyze_run(self.run)

        failure_lines = [
            line
            for line in captured.output
            if '"event": "ai_row_extraction_failed"' in line
        ]
        self.assertEqual(len(failure_lines), 2)
        payload = json.loads(failure_lines[0].split("ERROR:boq_ai.ai_rows:", 1)[1])
        self.assertEqual(payload["excel_row_number"], 1)
        self.assertEqual(payload["error"], "boom")
        self.assertIn("source_row", payload)

    @mock.patch("ai.extractors.analyzer.extract_boq_rows")
    def test_analyze_run_is_idempotent(self, extract_boq_rows_mock):
        def results(*args, **kwargs):
            return {
                str(row["row_id"]): {
                    "schema": "boq_ai_extraction_v1",
                    "database_products": [{"category": "Pipe"}],
                    "activities": ["excavation", "installation"],
                }
                for row in args[0]
            }

        extract_boq_rows_mock.side_effect = results

        analyze_run(self.run)
        analyze_run(self.run)

        # Re-running must not duplicate activity matches.
        self.assertEqual(ActivityMatch.objects.count(), 4)  # type: ignore[attr-defined]
