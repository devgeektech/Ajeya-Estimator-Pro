"""Product Id visibility and Analysis field prefilling."""
from django.test import SimpleTestCase

from apps.boq.services.boq_extraction_display_service import _shape_product
from apps.boq.services.make_vendor_common import loaded_catalog_product_id
from apps.boq.services.product_ai_common import _clear_weak_match_inputs
from common.constants import PRODUCT_ID_CONFIRM_CONFIDENCE


class LoadedCatalogProductIdTests(SimpleTestCase):
    def test_red_auto_match_hides_product_id(self):
        product = {
            "catalog_product_id": "20",
            "db_product_id": 100,
            "db_match_status": "matched",
            "db_match_confidence": 55.0,
            "ai_mapping": {"selection_source": "ai"},
        }
        self.assertEqual(loaded_catalog_product_id(product), "")
        self.assertLess(55.0, PRODUCT_ID_CONFIRM_CONFIDENCE)

    def test_orange_match_hides_product_id(self):
        product = {
            "catalog_product_id": "20",
            "db_product_id": 100,
            "db_match_status": "matched",
            "db_match_confidence": 74.0,
            "ai_mapping": {"selection_source": "ai"},
        }
        self.assertEqual(loaded_catalog_product_id(product), "")
        self.assertLess(74.0, PRODUCT_ID_CONFIRM_CONFIDENCE)

    def test_green_match_prefills_product_id_and_shows_confirm_manually(self):
        product = {
            "catalog_product_id": "20",
            "db_product_id": 100,
            "db_match_status": "matched",
            "db_match_confidence": 96.0,
            "ai_mapping": {"selection_source": "ai"},
        }
        # Products with green confidence score (>=95) come prefilled with product ID
        self.assertEqual(loaded_catalog_product_id(product), "20")

        # In UI shape, confirm manually is visible until manually confirmed at 100%
        # Also, green matches have status 'matched', no 'Suggested:' in summary, and no missing attribute count
        product["db_product_summary"] = "Suggested: 20 / VALVE / SLUICE / 150 / mm"
        product["missing_attribute_keys"] = ["mounting"]
        shaped = _shape_product(product, display_number=1, total=1, source_row_id="r1")
        self.assertTrue(shaped.get("show_confirm_match"))
        self.assertEqual(shaped["db_match"]["status"], "matched")
        self.assertEqual(shaped["db_match"]["summary"], "20 / VALVE / SLUICE / 150 / mm")
        self.assertEqual(shaped["missing_attribute_count"], 0)
        self.assertEqual(shaped["missing_attribute_keys"], [])

        # Products with 100% confidence score do not show confirm manually button
        product["ai_mapping"]["selection_source"] = "ai"
        product["db_match_confidence"] = 100.0
        shaped_100 = _shape_product(product, display_number=1, total=1, source_row_id="r1")
        self.assertFalse(shaped_100.get("show_confirm_match"))

    def test_expert_select_shows_product_id_even_if_red_pct(self):
        product = {
            "catalog_product_id": "20",
            "db_product_id": 100,
            "db_match_status": "matched",
            "db_match_confidence": 74.0,
            "ai_mapping": {"selection_source": "expert"},
        }
        self.assertEqual(loaded_catalog_product_id(product), "20")

    def test_provisional_hides_product_id(self):
        product = {
            "suggested_catalog_product_id": "20",
            "suggested_db_product_id": 100,
            "db_match_status": "provisional",
            "db_match_confidence": 74.0,
            "db_product_summary": "Suggested: 20 / PIPE / GI / C / 150.00 / mm",
            "ai_mapping": {"selection_source": "ai"},
        }
        self.assertEqual(loaded_catalog_product_id(product), "")


class WeakMatchPrefillTests(SimpleTestCase):
    def test_clear_weak_keeps_identity_and_attributes(self):
        product = {
            "category": "VALVE",
            "sub_category": "NON RETURN VALVE",
            "size": "200",
            "unit": "mm",
            "description_hint": "Cast iron non-return valve",
            "attribute_schema": ["PN"],
            "attributes": {"PN": "16"},
            "db_match_confidence": 29.0,
            "ai_mapping": {"selection_source": "ai"},
        }
        cleared = _clear_weak_match_inputs(product)
        self.assertEqual(cleared["category"], "VALVE")
        self.assertEqual(cleared["sub_category"], "NON RETURN VALVE")
        self.assertEqual(cleared["size"], "200")
        self.assertEqual(cleared["unit"], "mm")
        self.assertEqual(cleared["attributes"], {"PN": "16"})

    def test_shape_prefills_identity_and_attributes_on_low_confidence(self):
        shaped = _shape_product(
            {
                "product_index": 0,
                "description_hint": (
                    "Cast iron non-return valve (VALVE / NON RETURN VALVE), 200 mm dia"
                ),
                "category": "VALVE",
                "sub_category": "NON RETURN VALVE",
                "size": "200",
                "unit": "mm",
                "attributes": {"PN": "16"},
                "attribute_schema": ["PN"],
                "db_match_status": "provisional",
                "db_match_confidence": 29.0,
                "suggested_db_product_id": 5,
                "db_product_summary": "Suggested: 5 / PIPE / MS / C / 200.00 / mm",
                "db_candidates": [
                    {
                        "id": 5,
                        "product_id": "5",
                        "category": "PIPE",
                        "sub_category": "MS",
                        "class": "C",
                        "size": "200.00",
                        "unit": "mm",
                        "confidence": 29.0,
                    }
                ],
                "ai_mapping": {"selection_source": "ai"},
            },
            display_number=1,
            total=1,
            source_row_id="r1",
        )
        by_key = {field["key"]: field["value"] for field in shaped["fields"]}
        self.assertEqual(by_key["category"], "VALVE")
        self.assertEqual(by_key["sub_category"], "NON RETURN VALVE")
        self.assertEqual(by_key["size"], "200")
        self.assertEqual(by_key["unit"], "mm")
        self.assertEqual(by_key["product_id"], "")
        self.assertTrue(shaped.get("show_weak_match_warning"))
        attr_values = {
            field["key"]: field.get("value")
            for field in (shaped.get("attributes") or {}).get("fields") or []
        }
        self.assertEqual(attr_values.get("PN"), "16")

    def test_mismatched_inputs_flagged_for_products_above_50_confidence(self):
        # 1. Low-confidence product (<=50%) -> No mismatch highlighting even if values differ
        product_low_conf = {
            "product_index": 0,
            "description_hint": "AXE",
            "category": "HYDRANT",
            "sub_category": "FIRE MAN AXE",
            "size": "20",
            "unit": "Each",
            "capacity": None,
            "db_match_confidence": 29.0,
            "db_candidates": [
                {
                    "id": 10,
                    "category": "HYDRANT",
                    "sub_category": "FIRE MAN AXE",
                    "class": "FORGED STEEL",
                    "size": "10",
                    "unit": "Each",
                    "capacity": "0",
                    "confidence": 29.0,
                }
            ],
        }
        shaped_low = _shape_product(product_low_conf, display_number=1, total=1, source_row_id="r1")
        fields_low = {f["key"]: f for f in shaped_low["fields"]}
        self.assertFalse(fields_low["size"]["mismatched"])

        # 2. Product above 50% confidence -> Mismatch highlighted against highest confidence candidate!
        # Suggested product has size 10, AI extracted size 20 -> Mismatched!
        product_above_50 = {
            "product_index": 0,
            "description_hint": "AXE",
            "category": "HYDRANT",
            "sub_category": "FIRE MAN AXE",
            "size": "20",
            "unit": "Each",
            "capacity": None,
            "db_match_confidence": 85.0,
            "db_candidates": [
                {
                    "id": 10,
                    "category": "HYDRANT",
                    "sub_category": "FIRE MAN AXE",
                    "class": "FORGED STEEL",
                    "size": "10",
                    "unit": "Each",
                    "capacity": "0",
                    "confidence": 85.0,
                },
                {
                    "id": 11,
                    "category": "HYDRANT",
                    "sub_category": "FIRE MAN AXE",
                    "class": "FORGED STEEL",
                    "size": "20",
                    "unit": "Each",
                    "capacity": "0",
                    "confidence": 60.0,
                },
            ],
        }
        shaped_above_50 = _shape_product(product_above_50, display_number=1, total=1, source_row_id="r1")
        fields_above_50 = {f["key"]: f for f in shaped_above_50["fields"]}
        # Product ID is not filled for 85% (orange zone)
        self.assertEqual(fields_above_50["product_id"]["value"], "")
        # Size: AI extracted 20, top candidate (id 10, conf 85) has 10 -> Mismatched!
        self.assertTrue(fields_above_50["size"]["mismatched"])
        # Category and Sub-category match top candidate -> Not mismatched!
        self.assertFalse(fields_above_50["category"]["mismatched"])
        self.assertFalse(fields_above_50["sub_category"]["mismatched"])
        # Capacity: AI has None, candidate has 0 -> Both sentinel/empty -> Not mismatched!
        self.assertFalse(fields_above_50["capacity"]["mismatched"])

    def test_missing_product_ids_summary_separates_rate_only(self):
        from apps.boq.services.make_vendor_common import count_missing_product_ids_summary

        analysis = {
            "rows": [
                {
                    "row_id": "r1",
                    "products": [
                        {
                            "description_hint": "Normal product",
                            "rate_only": False,
                            "quantity": 10,
                            "ai_mapping": {"selection_source": "ai"},
                        },
                        {
                            "description_hint": "Rate only product",
                            "rate_only": True,
                            "quantity": "Rate Only",
                            "ai_mapping": {"selection_source": "ai"},
                        },
                    ],
                }
            ]
        }
        missing, rate_only = count_missing_product_ids_summary(analysis)
        self.assertEqual(missing, 2)
        self.assertEqual(rate_only, 1)

    def test_suggested_product_always_uses_highest_confidence_candidate(self):
        # Product has stale suggested_db_product_id = 113 (24% match),
        # but top candidate is 32 (56% match).
        # The suggested product banner must show 32, not 113!
        product = {
            "product_index": 0,
            "description_hint": "Landing valve 63mm",
            "category": "HYDRANT",
            "sub_category": "LANDING VALVE",
            "size": "63",
            "unit": "mm",
            "db_match_status": "provisional",
            "db_match_confidence": 56.0,
            "suggested_db_product_id": 113,
            "db_product_summary": "Suggested: 113 / HYDRANT / SHORT BRANCH PIPE / SS / 63.00 / mm / 0",
            "db_candidates": [
                {
                    "id": 32,
                    "product_id": "32",
                    "category": "HYDRANT",
                    "sub_category": "LANDING VALVE",
                    "class": "SS",
                    "size": "80.00",
                    "unit": "mm",
                    "confidence": 56.0,
                },
                {
                    "id": 30,
                    "product_id": "30",
                    "category": "HYDRANT",
                    "sub_category": "EXTERNAL HYDRANT",
                    "class": "SS",
                    "size": "63.00",
                    "unit": "mm",
                    "confidence": 53.0,
                },
                {
                    "id": 113,
                    "product_id": "113",
                    "category": "HYDRANT",
                    "sub_category": "SHORT BRANCH PIPE",
                    "class": "SS",
                    "size": "63.00",
                    "unit": "mm",
                    "confidence": 24.0,
                },
            ],
            "ai_mapping": {"selection_source": "ai"},
        }
        shaped = _shape_product(product, display_number=1, total=1, source_row_id="r1")
        self.assertIsNotNone(shaped["db_match"])
        self.assertEqual(shaped["db_match"]["suggested_id"], 32)
        self.assertIn("32 / HYDRANT / LANDING VALVE", shaped["db_match"]["summary"])
        self.assertNotIn("113 / HYDRANT / SHORT BRANCH PIPE", shaped["db_match"]["summary"])

