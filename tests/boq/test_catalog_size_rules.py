"""Catalog Size/Unit patterns aligned with Product_Helper."""

from django.test import SimpleTestCase

from utils.catalog_size_rules import (
    is_swg_gauge_number,
    parse_box_capacity_from_text,
    parse_length_from_text,
    parse_size_for_product,
    validate_size_unit_for_pattern,
)


class CatalogSizeRulesTests(SimpleTestCase):
    def test_parses_hose_length_not_coupling_diameter(self):
        text = (
            "Providing and fixing 63mm dia 15m fire hose, including Stainless steel "
            "male and female instantaneous type coupling"
        )
        size, unit = parse_size_for_product(
            text,
            category="HYDRANT",
            sub_category="FIRE HOSE",
            pattern={"units": ["m"], "sample_sizes": ["15.00"]},
        )
        self.assertEqual(size, "15")
        self.assertEqual(unit, "m")

    def test_branch_pipe_parses_outlet_mm(self):
        text = (
            "Providing and fixing standard short size Stainless steel branch pipe "
            "with hand operated gunmetal 20mm nominal bore outlet"
        )
        size, unit = parse_size_for_product(
            text,
            category="HYDRANT",
            sub_category="BRANCH PIPE",
            pattern={"units": ["mm"], "sample_sizes": ["20.00"]},
        )
        self.assertEqual(size, "20")
        self.assertEqual(unit, "mm")

    def test_rejects_swg_gauge_as_size(self):
        text = (
            "external fire hose box, made out of Mild Steel 18 SWG sheet, "
            "of approved colour of 30\"x24\"x10\" size"
        )
        self.assertTrue(is_swg_gauge_number("18", text))
        size, unit = parse_size_for_product(
            text,
            category="HYDRANT",
            sub_category="FIRE HOSE BOX",
            pattern={"units": ["inch"], "sample_sizes": ["0.00"]},
        )
        self.assertIsNone(size)
        self.assertIsNone(unit)

    def test_parses_box_capacity_dimensions(self):
        text = '30"x24"x10" size to accommodate two 15m length of delivery hoses'
        self.assertEqual(parse_box_capacity_from_text(text), "30X24X10")

    def test_clears_mm_size_on_fire_hose_family(self):
        product = {
            "category": "HYDRANT",
            "sub_category": "FIRE HOSE",
            "size": "63",
            "unit": "mm",
        }
        text = "63mm dia 15m fire hose"
        cleaned = validate_size_unit_for_pattern(
            product,
            evidence_text=text,
            pattern={"units": ["m"]},
        )
        self.assertIsNone(cleaned["size"])
        self.assertIsNone(cleaned["unit"])

    def test_clears_swg_guessed_size(self):
        product = {"category": "HYDRANT", "sub_category": "BRANCH PIPE", "size": "18", "unit": "mm"}
        text = "Mild Steel 18 SWG sheet, branch pipes with glass fronted double door"
        cleaned = validate_size_unit_for_pattern(
            product,
            evidence_text=text,
            pattern={"units": ["mm"]},
        )
        self.assertIsNone(cleaned["size"])

    def test_parse_length_variants(self):
        self.assertEqual(parse_length_from_text("two 15m length of delivery hoses"), ("15", "m"))
        self.assertEqual(parse_length_from_text("hose 15 m long"), ("15", "m"))
