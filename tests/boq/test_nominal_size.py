"""Nominal size parsing — ignore IS standard numbers; uncertain → null."""

from django.test import SimpleTestCase

from apps.boq.services.boq_extraction_fields import normalize_product_fields
from utils.nominal_size import (
    is_invalid_extracted_size,
    parse_nominal_size_from_text,
    sanitize_product_size,
)


class NominalSizeParseTests(SimpleTestCase):
    def test_prefers_mm_dia_over_is_standard(self):
        text = (
            "Providing hose conforming to IS : 636-1979 (Type -A) of "
            "63 mm dia and 15 m length"
        )
        size, unit = parse_nominal_size_from_text(text)
        self.assertEqual(size, "63")
        self.assertEqual(unit, "mm")

    def test_strict_mode_requires_explicit_unit(self):
        text = "Providing hose conforming to IS : 636-1979 of 63 mm dia"
        size, unit = parse_nominal_size_from_text(text, require_explicit_unit=True)
        self.assertEqual(size, "63")
        self.assertEqual(unit, "mm")

    def test_is_standard_number_not_parsed_as_size(self):
        size, unit = parse_nominal_size_from_text("conforming to IS:903-1975")
        self.assertIsNone(size)
        self.assertIsNone(unit)

    def test_detects_is_literal_as_invalid_size(self):
        self.assertTrue(is_invalid_extracted_size("IS"))

    def test_detects_is_number_confusion(self):
        text = "hose pipe IS : 636-1979, 63 mm dia"
        self.assertTrue(
            is_invalid_extracted_size(
                "636",
                context_text=text,
                attributes={"is": "636"},
            )
        )

    def test_sanitize_clears_invalid_size_without_substitution(self):
        product = {
            "size": "636",
            "unit": "mm",
            "description_hint": (
                "class SYNTHETIC (RRL) fire hose (HYDRANT), 63 mm dia, capacity 15 m"
            ),
            "attributes": {"is": "636"},
        }
        sanitized = sanitize_product_size(product)
        self.assertIsNone(sanitized["size"])

    def test_normalize_product_fields_clears_invalid_is_size(self):
        product = {
            "size": "636",
            "unit": "mm",
            "description_hint": "fire hose, 63 mm dia, IS 636",
            "attributes": {"is": "636"},
        }
        normalized = normalize_product_fields(product)
        self.assertIsNone(normalized["size"])

    def test_valid_size_is_unchanged(self):
        product = {
            "size": "63",
            "unit": "mm",
            "description_hint": "fire hose, 63 mm dia",
            "attributes": {"is": "636"},
        }
        normalized = normalize_product_fields(product)
        self.assertEqual(normalized["size"], "63")
