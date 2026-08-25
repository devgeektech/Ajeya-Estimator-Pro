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
            "db_match_confidence": 74.0,
            "ai_mapping": {"selection_source": "ai"},
        }
        self.assertEqual(loaded_catalog_product_id(product), "")
        self.assertLess(74.0, PRODUCT_ID_CONFIRM_CONFIDENCE)

    def test_green_match_shows_product_id(self):
        product = {
            "catalog_product_id": "20",
            "db_product_id": 100,
            "db_match_status": "matched",
            "db_match_confidence": 96.0,
            "ai_mapping": {"selection_source": "ai"},
        }
        self.assertEqual(loaded_catalog_product_id(product), "20")

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
