from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model

from apps.boq.models import BOQ
from apps.boq.services.boq_extraction_display_service import _shape_product
from apps.boq.services.boq_extraction_edit_service import BOQExtractionEditService
from apps.boq.services.boq_row_fields import resolve_activity_only
from apps.boq.services.make_vendor_common import count_missing_loaded_product_ids
from common.choices import BOQStatus

User = get_user_model()


class ResolveActivityOnlyTests(SimpleTestCase):
    def test_any_product_clears_job_only(self):
        self.assertFalse(
            resolve_activity_only(
                {"is_activity_only": True},
                products=[{"description_hint": "pipe"}],
                units=["Job"],
            )
        )

    def test_empty_with_flag_is_job_only(self):
        self.assertTrue(
            resolve_activity_only(
                {"is_activity_only": True},
                products=[],
                units=["No."],
            )
        )

    def test_job_unit_empty_inferred(self):
        self.assertTrue(resolve_activity_only({}, products=[], units=["Job"]))

    def test_non_job_empty_not_inferred(self):
        self.assertFalse(resolve_activity_only({}, products=[], units=["No."]))


class ProductIdDisplayTests(SimpleTestCase):
    def test_product_id_field_is_readonly_before_category(self):
        shaped = _shape_product(
            {
                "product_index": 0,
                "description_hint": "pipe",
                "category": "PIPE",
                "catalog_product_id": "6",
                "db_product_id": 100,
                "db_match_status": "matched",
                "db_match_confidence": 100,
            },
            display_number=1,
            total=1,
            source_row_id="r1",
        )
        keys = [field["key"] for field in shaped["fields"]]
        self.assertEqual(keys[0], "description_hint")
        self.assertEqual(keys[1], "product_id")
        self.assertEqual(keys[2], "category")
        product_id_field = shaped["fields"][1]
        self.assertTrue(product_id_field["readonly"])
        self.assertEqual(product_id_field["value"], "6")
        self.assertEqual(shaped["catalog_product_id"], "6")

    def test_count_missing_loaded_product_ids(self):
        analysis = {
            "rows": [
                {
                    "row_id": "r1",
                    "products": [
                        {
                            "catalog_product_id": "6",
                            "db_product_id": 1,
                            "db_match_status": "matched",
                            "db_match_confidence": 96.0,
                            "ai_mapping": {"selection_source": "ai"},
                        },
                        {"description_hint": "blank"},
                    ],
                },
                {"row_id": "r2", "is_activity_only": True, "products": []},
            ]
        }
        self.assertEqual(count_missing_loaded_product_ids(analysis), 1)


class ExtractionEditActivityOnlyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="password")
        self.boq = BOQ.objects.create(
            boq_name="Job Only Edit BOQ",
            status=BOQStatus.EXTRACTED,
            user=self.user,
            boq_data={"rows": [{"row_id": "r1", "serial": "1.11"}]},
            analysis_data={
                "rows": [
                    {
                        "row_id": "r1",
                        "skip_matching": True,
                        "products": [],
                        "is_activity_only": True,
                    }
                ]
            },
        )
        self.editor = BOQExtractionEditService(self.boq.pk)

    def test_add_product_clears_job_only(self):
        product = self.editor.add_product(row_id="r1")
        self.boq.refresh_from_db()
        row = (self.boq.analysis_data or {}).get("rows")[0]
        self.assertFalse(row.get("is_activity_only"))
        self.assertFalse(row.get("skip_matching"))
        self.assertEqual(len(row.get("products") or []), 1)
        self.assertEqual(product.get("product_index"), 0)

    def test_remove_last_product_marks_job_only(self):
        self.editor.add_product(row_id="r1")
        self.editor.remove_product(row_id="r1", product_index=0)
        self.boq.refresh_from_db()
        row = (self.boq.analysis_data or {}).get("rows")[0]
        self.assertTrue(row.get("is_activity_only"))
        self.assertTrue(row.get("skip_matching"))
        self.assertEqual(row.get("products") or [], [])


class AnalysisNextProductIdGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="gate@example.com", password="password"
        )
        self.boq = BOQ.objects.create(
            boq_name="Next Gate BOQ",
            status=BOQStatus.EXTRACTED,
            user=self.user,
            boq_data={"rows": [{"row_id": "r1", "serial": "1"}]},
            analysis_data={
                "rows": [
                    {
                        "row_id": "r1",
                        "products": [
                            {
                                "product_index": 0,
                                "description_hint": "pipe",
                            }
                        ],
                    }
                ]
            },
        )

    def test_next_marks_weak_match_without_loaded_id_not_available(self):
        from apps.boq.services.make_vendor_common import (
            NOT_AVAILABLE_SOURCE,
            NOT_AVAILABLE_STATUS,
        )
        from apps.boq.services.make_vendor_selection_service import MakeVendorSelectionService

        self.boq.analysis_data = {
            "rows": [
                {
                    "row_id": "r1",
                    "products": [
                        {
                            "product_index": 0,
                            "description_hint": "branch pipe",
                            "category": "HYDRANT",
                            "sub_category": "BRANCH PIPE",
                            "db_match_status": "matched",
                            "db_match_confidence": 42.0,
                            "db_product_id": 2301,
                            "suggested_catalog_product_id": "33",
                            "catalog_product_id": "33",
                        }
                    ],
                }
            ]
        }
        self.boq.save(update_fields=["analysis_data"])

        service = MakeVendorSelectionService(self.boq.pk, {})
        result = service.apply_lowest_defaults_all(find_rates=False)
        self.assertGreaterEqual(int(result.get("not_available_count") or 0), 1)

        self.boq.refresh_from_db()
        product = self.boq.analysis_data["rows"][0]["products"][0]
        selection = product.get("vendor_selection") or {}
        self.assertEqual(selection.get("status"), NOT_AVAILABLE_STATUS)
        self.assertEqual(product.get("vendor_selection_source"), NOT_AVAILABLE_SOURCE)
        self.assertFalse(selection.get("rate_detail"))
        self.assertFalse(product.get("catalog_product_id"))

    def test_next_marks_missing_product_id_not_available(self):
        from apps.boq.services.make_vendor_common import (
            NOT_AVAILABLE_SOURCE,
            NOT_AVAILABLE_STATUS,
        )
        from apps.boq.services.make_vendor_selection_service import MakeVendorSelectionService

        service = MakeVendorSelectionService(self.boq.pk, {})
        result = service.apply_lowest_defaults_all(find_rates=False)
        self.assertGreaterEqual(int(result.get("not_available_count") or 0), 1)

        self.boq.refresh_from_db()
        product = self.boq.analysis_data["rows"][0]["products"][0]
        selection = product.get("vendor_selection") or {}
        self.assertEqual(selection.get("status"), NOT_AVAILABLE_STATUS)
        self.assertEqual(product.get("vendor_selection_source"), NOT_AVAILABLE_SOURCE)
        self.assertFalse(selection.get("rate_detail"))
        self.assertFalse(selection.get("labour_detail"))
