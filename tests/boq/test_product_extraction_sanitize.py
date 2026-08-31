"""Evidence-based sanitization — null when uncertain, never guess."""

from django.test import SimpleTestCase

from utils.product_extraction_sanitize import sanitize_product_against_evidence

_TEST_TAXONOMY = {
    "categories": ["PIPE", "VALVE", "SPRINKLER", "HYDRANT"],
    "sub_categories_by_category": {
        "SPRINKLER": ["UPRIGHT"],
        "VALVE": ["SLUICE VALVE"],
        "HYDRANT": ["FIRE HOSE"],
    },
    "classes_by_category_sub_category": {
        "VALVE": {"SLUICE VALVE": ["0"]},
    },
}


class ProductExtractionSanitizeTests(SimpleTestCase):
    def test_clears_guessed_make_hint_not_in_evidence(self):
        product = {
            "make_hint": "Tyco",
            "category": "SPRINKLER",
            "sub_category": "UPRIGHT",
        }
        context = "Providing upright sprinkler head, 15 mm orifice"
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=context,
            slot_desc="a) 15 mm orifice upright",
            evidence_text=context,
            taxonomy=_TEST_TAXONOMY,
        )
        self.assertIsNone(sanitized["make_hint"])

    def test_keeps_make_hint_when_in_evidence(self):
        product = {"make_hint": "Tyco", "category": "SPRINKLER", "sub_category": "UPRIGHT"}
        context = "Tyco upright sprinkler head, 15 mm orifice"
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=context,
            slot_desc="a) Tyco upright 15 mm",
            evidence_text=context,
            taxonomy=_TEST_TAXONOMY,
        )
        self.assertEqual(sanitized["make_hint"], "Tyco")

    def test_clears_wrong_pn_capacity_without_substitution(self):
        product = {
            "capacity": "PN25",
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
            "class": "0",
        }
        context = "Cast Iron sluice valve PN16, 250 mm dia"
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=context,
            slot_desc="a) 250 mm dia",
            evidence_text=context,
            taxonomy=_TEST_TAXONOMY,
        )
        self.assertIsNone(sanitized["capacity"])

    def test_fills_pn_capacity_only_when_blank(self):
        product = {
            "capacity": None,
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
            "class": "0",
        }
        context = "Cast Iron sluice valve PN16, 250 mm dia"
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=context,
            slot_desc="a) 250 mm dia",
            evidence_text=context,
            taxonomy=_TEST_TAXONOMY,
        )
        self.assertEqual(sanitized["capacity"], "PN16")

    def test_clears_is_attribute_guessed_from_unrelated_number(self):
        product = {
            "size": None,
            "attributes": {"is": "1979"},
        }
        context = (
            "Providing hose conforming to IS : 636-1979 (Type -A) of "
            "63 mm dia and 15 m length"
        )
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=context,
            slot_desc="a) 63 mm dia hose",
            evidence_text=context,
            taxonomy=_TEST_TAXONOMY,
        )
        self.assertIsNone(sanitized["attributes"]["is"])

    def test_keeps_is_attribute_when_in_evidence(self):
        product = {
            "size": "63",
            "unit": "mm",
            "attributes": {"is": "636"},
        }
        context = (
            "Providing hose conforming to IS : 636-1979 (Type -A) of "
            "63 mm dia and 15 m length"
        )
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=context,
            slot_desc="a) 63 mm dia hose",
            evidence_text=context,
            taxonomy=_TEST_TAXONOMY,
        )
        self.assertEqual(sanitized["attributes"]["is"], "636")

    def test_clears_invalid_category_not_in_taxonomy(self):
        product = {
            "category": "NOT_A_REAL_CATEGORY",
            "sub_category": "FOO",
        }
        sanitized = sanitize_product_against_evidence(
            product,
            product_context="some line",
            slot_desc="a) item",
            evidence_text="some line",
            taxonomy={
                "categories": ["PIPE", "VALVE"],
                "sub_categories_by_category": {"PIPE": ["MS", "GI"]},
                "classes_by_category_sub_category": {},
            },
        )
        self.assertIsNone(sanitized["category"])

    def test_clears_guessed_attribute_not_in_evidence(self):
        product = {
            "category": "HYDRANT",
            "sub_category": "FIRE HOSE",
            "attributes": {"colour": "red"},
        }
        context = "RRL fire hose, 63 mm dia, IS 636"
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=context,
            slot_desc="a) 63 mm dia",
            evidence_text=context,
            taxonomy=_TEST_TAXONOMY,
        )
        self.assertIsNone(sanitized["attributes"].get("colour"))

    def test_clears_is_number_as_size_and_refills_bore(self):
        context = (
            "Providing and fixing first aid fire hose reel (with wall mounting "
            "swinging-type drum complying to IS:884), fitted with Thermo Plastic "
            "Synthetic Reinforced Fire Hoses conforming to IS:12585-1988 ( of "
            "Type -2 class, 20 mm bore, with standard size outlet and shut off valve"
        )
        product = {
            "category": "HYDRANT",
            "sub_category": "FIRE HOSE REEL",
            "class": "TYPE 2",
            "size": "884",
            "unit": "mm",
            "attributes": {"is": "12585", "type": "swinging"},
        }
        sanitized = sanitize_product_against_evidence(
            product,
            product_context=context,
            slot_desc="a) Each",
            evidence_text=context,
            taxonomy={
                "categories": ["HYDRANT"],
                "sub_categories_by_category": {"HYDRANT": ["FIRE HOSE REEL"]},
                "classes_by_category_sub_category": {
                    "HYDRANT": {"FIRE HOSE REEL": ["TYPE 2"]},
                },
            },
        )
        self.assertEqual(sanitized["size"], "20")
        self.assertEqual(sanitized["unit"], "mm")
