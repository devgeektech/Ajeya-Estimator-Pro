"""Unit tests for product availability promotion rules."""
from django.test import SimpleTestCase

from apps.boq.services.make_list_constraint_service import NO_APPROVED_MAKE_LABEL
from apps.boq.services.make_vendor_common import (
    NOT_AVAILABLE_LABEL,
    NOT_AVAILABLE_STATUS,
)
from apps.boq.services.product_availability import (
    REASON_NO_LABOUR,
    REASON_NOT_IN_DB,
    REASON_NOT_LISTED,
    count_labour_confirm_buckets,
    has_positive_labour,
    is_not_in_db,
    is_not_listed,
    mark_product_not_available,
    promote_missing_labour_for_review,
    promote_unresolved_for_labour,
    will_become_not_available_on_labour,
)


class ProductAvailabilityTests(SimpleTestCase):
    def test_not_listed_and_not_in_db_detection(self):
        listed = {
            "vendor_selection_source": "not_found",
            "vendor_selection": {"status": "unmatched", "notes": NO_APPROVED_MAKE_LABEL},
        }
        in_db_miss = {
            "vendor_selection_source": "lowest_defaults",
            "vendor_selection": {"status": "unmatched"},
        }
        matched = {
            "vendor_selection_source": "lowest_defaults",
            "vendor_selection": {"status": "matched", "line_output": {"labour_rate": 10}},
        }
        self.assertTrue(is_not_listed(listed))
        self.assertFalse(is_not_in_db(listed))
        self.assertTrue(is_not_in_db(in_db_miss))
        self.assertTrue(will_become_not_available_on_labour(listed))
        self.assertTrue(will_become_not_available_on_labour(in_db_miss))
        self.assertFalse(will_become_not_available_on_labour(matched))

    def test_promote_unresolved_for_labour(self):
        analysis = {
            "rows": [
                {
                    "row_id": "r1",
                    "products": [
                        {
                            "product_index": 0,
                            "vendor_selection_source": "not_found",
                            "vendor_selection": {
                                "status": "unmatched",
                                "notes": NO_APPROVED_MAKE_LABEL,
                            },
                        },
                        {
                            "product_index": 1,
                            "vendor_selection_source": "lowest_defaults",
                            "vendor_selection": {"status": "unmatched"},
                        },
                        {
                            "product_index": 2,
                            "vendor_selection_source": "lowest_defaults",
                            "vendor_selection": {
                                "status": "matched",
                                "line_output": {"labour_rate": 5, "material_rate": 10},
                            },
                        },
                    ],
                }
            ]
        }
        buckets = count_labour_confirm_buckets(analysis)
        self.assertEqual(buckets["not_listed_count"], 1)
        self.assertEqual(buckets["not_in_db_count"], 1)
        result = promote_unresolved_for_labour(analysis)
        self.assertEqual(result["promoted_count"], 2)
        products = analysis["rows"][0]["products"]
        self.assertEqual(products[0]["vendor_selection"]["status"], NOT_AVAILABLE_STATUS)
        self.assertEqual(products[0]["not_available_reason"], REASON_NOT_LISTED)
        self.assertEqual(products[1]["not_available_reason"], REASON_NOT_IN_DB)
        self.assertEqual(products[2]["vendor_selection"]["status"], "matched")

    def test_promote_missing_labour_for_review(self):
        analysis = {
            "rows": [
                {
                    "row_id": "r1",
                    "products": [
                        {
                            "product_index": 0,
                            "vendor_selection": {
                                "status": "matched",
                                "line_output": {
                                    "material_rate": 100,
                                    "labour_rate": None,
                                    "total_amount": 100,
                                },
                            },
                        }
                    ],
                }
            ]
        }
        self.assertFalse(has_positive_labour(analysis["rows"][0]["products"][0]))
        result = promote_missing_labour_for_review(analysis)
        self.assertEqual(result["promoted_count"], 1)
        product = analysis["rows"][0]["products"][0]
        self.assertEqual(product["vendor_selection"]["status"], NOT_AVAILABLE_STATUS)
        self.assertEqual(product["not_available_reason"], REASON_NO_LABOUR)
        marked = mark_product_not_available(
            {"vendor_selection": {"status": "matched"}},
            reason=REASON_NO_LABOUR,
        )
        self.assertEqual(
            marked["vendor_selection"]["notes"],
            "Not available — no labour charge found.",
        )
        self.assertEqual(NOT_AVAILABLE_LABEL, "Not available")
