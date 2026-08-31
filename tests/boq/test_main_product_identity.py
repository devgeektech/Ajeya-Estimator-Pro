"""Main product identity — enclosure beats contents (branch pipe in hose box line)."""

from django.test import SimpleTestCase

from apps.boq.services.product_matching_service import ProductMatchingService, structured_match_score
from utils.catalog_size_rules import (
    normalize_main_product_identity,
    resolve_main_product_from_evidence,
)
from utils.product_extraction_sanitize import sanitize_product_against_evidence

_HOSE_BOX_TEXT = (
    "Providing and fixing external fire hose box, wall mounting or free standing type, "
    "made out of Mild Steel 18 SWG sheet, of approved colour of 30x24x10 size to "
    "accommodate two 15m length of delivery hoses and a branch pipes with glass "
    "fronted double door"
)

_TEST_TAXONOMY = {
    "categories": ["HYDRANT"],
    "sub_categories_by_category": {
        "HYDRANT": ["FIRE HOSE BOX", "BRANCH PIPE", "FIRE HOSE"],
    },
    "classes_by_category_sub_category": {
        "HYDRANT": {
            "FIRE HOSE BOX": ["MS"],
            "BRANCH PIPE": ["SS"],
        },
    },
}


class MainProductIdentityTests(SimpleTestCase):
    def test_resolves_fire_hose_box_not_branch_pipe(self):
        cat, sub = resolve_main_product_from_evidence(_HOSE_BOX_TEXT)
        self.assertEqual(cat, "HYDRANT")
        self.assertEqual(sub, "FIRE HOSE BOX")

    def test_sanitize_corrects_branch_pipe_to_hose_box(self):
        product = {
            "category": "HYDRANT",
            "sub_category": "BRANCH PIPE",
            "class": "SS",
            "size": "18",
            "unit": "mm",
            "attributes": {"is": "903", "type": "short branch pipe"},
        }
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=_HOSE_BOX_TEXT,
            slot_desc=_HOSE_BOX_TEXT,
            evidence_text=_HOSE_BOX_TEXT,
            taxonomy=_TEST_TAXONOMY,
            size_patterns=[
                {
                    "category": "HYDRANT",
                    "sub_category": "FIRE HOSE BOX",
                    "units": ["inch"],
                    "sample_sizes": ["0.00"],
                    "sample_capacities": ["30X24X10"],
                }
            ],
        )
        self.assertEqual(sanitized["sub_category"], "FIRE HOSE BOX")
        self.assertEqual(sanitized["class"], "MS")
        self.assertIsNone(sanitized["size"])
        self.assertEqual(sanitized["capacity"], "30X24X10")

    def test_normalize_main_product_clears_branch_pipe_attrs(self):
        product = {
            "category": "HYDRANT",
            "sub_category": "BRANCH PIPE",
            "class": "SS",
            "size": "18",
            "unit": "mm",
            "attributes": {"is": "903", "type": "short branch pipe"},
        }
        fixed = normalize_main_product_identity(product, evidence_text=_HOSE_BOX_TEXT)
        self.assertEqual(fixed["sub_category"], "FIRE HOSE BOX")
        self.assertIsNone(fixed["attributes"]["type"])

    def test_rematch_refresh_corrects_branch_pipe_fields(self):
        from unittest.mock import patch

        from apps.boq.services.boq_extraction_slots import refresh_product_from_boq_context

        product = {
            "category": "HYDRANT",
            "sub_category": "BRANCH PIPE",
            "class": "SS",
            "size": "18",
            "unit": "mm",
            "capacity": "0",
            "description_hint": "class SS branch pipe (hydrant), 18",
            "attributes": {"is": "903", "type": "short branch pipe"},
        }
        patterns = [
            {
                "category": "HYDRANT",
                "sub_category": "FIRE HOSE BOX",
                "units": ["inch"],
                "sample_sizes": ["0.00"],
                "sample_capacities": ["30X24X10"],
            }
        ]
        with patch("ai.context.load_rate_master_taxonomy", return_value=_TEST_TAXONOMY):
            refreshed = refresh_product_from_boq_context(
                product,
                boq_row={"description": _HOSE_BOX_TEXT, "slot_description": _HOSE_BOX_TEXT},
                taxonomy=_TEST_TAXONOMY,
                size_patterns=patterns,
            )
        self.assertEqual(refreshed.get("sub_category"), "FIRE HOSE BOX")
        self.assertEqual(refreshed.get("class"), "MS")
        self.assertIsNone(refreshed.get("size"))
        self.assertIn("fire hose box", str(refreshed.get("description_hint") or "").lower())
