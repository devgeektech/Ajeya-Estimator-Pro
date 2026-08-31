"""Normalize FIRE HOSE length from capacity to size."""

from django.test import SimpleTestCase

from apps.boq.services.boq_extraction_fields import normalize_product_fields
from utils.catalog_size_rules import normalize_catalog_size_capacity


class NormalizeCatalogSizeCapacityTests(SimpleTestCase):
    def test_moves_length_from_capacity_to_size_for_fire_hose(self):
        product = {
            "category": "HYDRANT",
            "sub_category": "FIRE HOSE",
            "class": "SYNTHETIC (RRL)",
            "size": None,
            "unit": "m",
            "capacity": "15",
            "description_hint": "fire hose (HYDRANT / FIRE HOSE), 15 m length, 63 mm dia",
        }
        normalized = normalize_catalog_size_capacity(
            product,
            pattern={"units": ["m"], "sample_sizes": ["15.00"]},
            evidence_text="63mm dia 15m fire hose",
        )
        self.assertEqual(normalized["size"], "15")
        self.assertIsNone(normalized["capacity"])

    def test_normalize_product_fields_moves_fire_hose_length(self):
        product = {
            "category": "HYDRANT",
            "sub_category": "FIRE HOSE",
            "unit": "m",
            "size": None,
            "capacity": "15",
            "description_hint": "fire hose, 15 m length",
        }
        normalized = normalize_product_fields(product)
        self.assertEqual(normalized["size"], "15")
        self.assertIsNone(normalized["capacity"])
