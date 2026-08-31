"""AI Description identity must not match a conflicting Rate_Master family."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.boq.services.product_ai_apply import (
    ProductAIApplyMixin,
    _ai_notes_reject_match,
)
from apps.boq.services.product_matching_service import (
    product_type_conflicts,
    structured_match_score,
)


def _rate(**kwargs):
    defaults = {
        "Category": "PIPE",
        "Sub_Category": "GI",
        "Class": "C",
        "Size": "100",
        "Unit": "mm",
        "Capacity": "0",
        "Attribute": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class ProductTypeConflictTests(SimpleTestCase):
    def test_sluice_hint_conflicts_with_pipe_row(self):
        extracted = {
            "description_hint": "sluice valve, 250 mm dia",
            "category": "PIPE",
            "sub_category": "GI",
            "size": "250",
        }
        self.assertTrue(product_type_conflicts(extracted, _rate()))

    def test_agreeing_wrong_category_does_not_clear_hint_conflict(self):
        extracted = {
            "description_hint": "cast iron sluice valve, 250 mm dia",
            "category": "PIPE",
            "sub_category": "GI",
        }
        self.assertTrue(
            product_type_conflicts(
                extracted, _rate(Category="PIPE", Sub_Category="GI")
            )
        )

    def test_valve_hint_matches_valve_row(self):
        extracted = {
            "description_hint": "cast iron sluice valve, 250 mm dia",
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
        }
        rate = _rate(Category="VALVE", Sub_Category="SLUICE VALVE", Class="0")
        self.assertFalse(product_type_conflicts(extracted, rate))

    def test_pipe_hint_matches_pipe_row(self):
        extracted = {
            "description_hint": "GI pipe, 250 mm dia, class C",
            "category": "PIPE",
            "sub_category": "GI",
        }
        self.assertFalse(product_type_conflicts(extracted, _rate()))

    def test_butterfly_conflicts_with_sluice_row(self):
        extracted = {
            "description_hint": "butterfly valve, 65 mm dia, PN16",
            "category": "VALVE",
            "sub_category": "BUTTERFLY",
        }
        rate = _rate(Category="VALVE", Sub_Category="SLUICE VALVE", Class="0")
        self.assertTrue(product_type_conflicts(extracted, rate))

    def test_check_valve_conflicts_with_sluice_row(self):
        extracted = {
            "description_hint": "200mm dia check valve",
            "category": "VALVE",
            "sub_category": "NON RETURN VALVE",
        }
        rate = _rate(Category="VALVE", Sub_Category="SLUICE VALVE", Class="0")
        self.assertTrue(product_type_conflicts(extracted, rate))

    def test_reflux_conflicts_with_sluice_row(self):
        extracted = {
            "description_hint": "reflux type check valve (non return), 200 mm dia",
            "category": "VALVE",
            "sub_category": "NON RETURN VALVE",
        }
        rate = _rate(Category="VALVE", Sub_Category="SLUICE VALVE", Class="0")
        self.assertTrue(product_type_conflicts(extracted, rate))

    def test_fire_hose_box_conflicts_with_fire_hose_row(self):
        extracted = {
            "description_hint": "class MS fire hose box (hydrant), capacity 30X24X10",
            "category": "HYDRANT",
            "sub_category": "FIRE HOSE BOX",
        }
        hose = _rate(Category="HYDRANT", Sub_Category="FIRE HOSE", Class="SYNTHETIC (RRL)")
        box = _rate(Category="HYDRANT", Sub_Category="FIRE HOSE BOX", Class="MS")
        self.assertTrue(product_type_conflicts(extracted, hose))
        self.assertFalse(product_type_conflicts(extracted, box))

    def test_conflict_score_capped_below_match_threshold(self):
        extracted = {
            "description_hint": "sluice valve, 250 mm dia",
            "category": "PIPE",
            "sub_category": "GI",
            "class": "C",
            "size": "250",
            "unit": "mm",
        }
        rate = _rate(
            Category="PIPE",
            Sub_Category="GI",
            Class="C",
            Size="250",
            Unit="mm",
        )
        score, breakdown = structured_match_score(extracted, rate)
        self.assertTrue(breakdown.get("description_type_mismatch"))
        self.assertLess(score, 30.0)


class AiNotesRejectTests(SimpleTestCase):
    def test_no_suitable_candidate_notes(self):
        self.assertTrue(
            _ai_notes_reject_match("No suitable candidate for sluice valve.")
        )
        self.assertTrue(
            _ai_notes_reject_match(
                "No suitable candidate matches the butterfly valve requirement."
            )
        )
        self.assertFalse(_ai_notes_reject_match("Size and sub-category align."))


class FirstNonConflictingRateTests(SimpleTestCase):
    def test_skips_conflicting_top_candidate(self):
        enriched = {
            "description_hint": "sluice valve, 250 mm dia",
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
        }
        pipe = _rate(Category="PIPE", Sub_Category="GI", Class="C")
        valve = _rate(Category="VALVE", Sub_Category="SLUICE VALVE", Class="0")
        rate_map = {18: pipe, 99: valve}
        candidates = [
            {"id": 18, "confidence": 100.0},
            {"id": 99, "confidence": 80.0},
        ]
        chosen = ProductAIApplyMixin._first_non_conflicting_rate_id(
            18,
            enriched=enriched,
            candidates=candidates,
            rate_map=rate_map,
            rematch=False,
        )
        self.assertEqual(chosen, 99)

    def test_all_conflicting_returns_none(self):
        enriched = {
            "description_hint": "butterfly valve, 65 mm dia",
            "category": "VALVE",
            "sub_category": "BUTTERFLY",
        }
        rate_map = {
            1: _rate(Category="VALVE", Sub_Category="SLUICE VALVE", Class="0"),
            2: _rate(Category="PIPE", Sub_Category="MS", Class="C"),
        }
        candidates = [
            {"id": 1, "confidence": 100.0},
            {"id": 2, "confidence": 90.0},
        ]
        chosen = ProductAIApplyMixin._first_non_conflicting_rate_id(
            1,
            enriched=enriched,
            candidates=candidates,
            rate_map=rate_map,
            rematch=False,
        )
        self.assertIsNone(chosen)
