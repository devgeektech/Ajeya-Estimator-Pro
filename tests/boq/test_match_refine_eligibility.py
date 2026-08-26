"""Analyse refine eligibility (speed: skip non-weak rematch)."""
from django.test import SimpleTestCase

from apps.boq.services.product_ai_common import product_needs_match_refine
from common.constants import MATCH_CONFIDENCE_THRESHOLD


class ProductNeedsMatchRefineTests(SimpleTestCase):
    def test_provisional_above_threshold_skips_refine(self):
        product = {
            "db_match_status": "provisional",
            "db_match_confidence": 45.0,
        }
        self.assertFalse(
            product_needs_match_refine(
                product, min_confidence=MATCH_CONFIDENCE_THRESHOLD
            )
        )

    def test_weak_confidence_needs_refine(self):
        product = {
            "db_match_status": "provisional",
            "db_match_confidence": 29.0,
        }
        self.assertTrue(
            product_needs_match_refine(
                product, min_confidence=MATCH_CONFIDENCE_THRESHOLD
            )
        )

    def test_matched_below_threshold_needs_refine(self):
        product = {
            "db_match_status": "matched",
            "db_match_confidence": 20.0,
        }
        self.assertTrue(
            product_needs_match_refine(
                product, min_confidence=MATCH_CONFIDENCE_THRESHOLD
            )
        )

    def test_strong_matched_skips_refine(self):
        product = {
            "db_match_status": "matched",
            "db_match_confidence": 88.0,
        }
        self.assertFalse(
            product_needs_match_refine(
                product, min_confidence=MATCH_CONFIDENCE_THRESHOLD
            )
        )
