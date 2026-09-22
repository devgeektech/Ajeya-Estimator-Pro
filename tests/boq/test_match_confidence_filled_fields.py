"""Match confidence: filled-field weightage + empty inputs stay empty."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from ai.context import align_product_taxonomy_from_rate, fill_product_core_fields_from_rate
from apps.boq.services.product_ai_candidates import (
    ProductAICandidatesMixin,
    _append_section_to_recall_hint,
)
from apps.boq.services.product_ai_common import _schema_attributes_from_rate
from apps.boq.services.product_matching_service import structured_match_score


def _rate(**kwargs):
    defaults = {
        "Category": "VALVE",
        "Sub_Category": "SLUICE VALVE",
        "Class": "0",
        "Size": "150",
        "Unit": "mm",
        "Capacity": "",
        "Attribute": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class StructuredScoreFilledFieldsTests(SimpleTestCase):
    def test_matching_filled_fields_score_high(self):
        extracted = {
            "description_hint": "sluice valve 150 mm dia class 0",
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
            "class": "0",
            "size": "150",
            "unit": "mm",
        }
        rate = _rate()
        score, breakdown = structured_match_score(extracted, rate)
        self.assertGreaterEqual(score, 90.0)
        self.assertIsNone(breakdown.get("thin_identity_cap"))

    def test_blank_fields_do_not_dilute_matching_identity(self):
        """Unfound class/capacity must not drag a correct cat/sub/size match to ~40%."""
        extracted = {
            "description_hint": "sluice valve 150 mm",
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
            "size": "150",
            "unit": "mm",
            # class / capacity intentionally blank
        }
        rate = _rate(Class="0", Capacity="PN16")
        score, _ = structured_match_score(extracted, rate)
        self.assertGreaterEqual(score, 80.0)

    def test_size_unit_only_capped(self):
        extracted = {
            "description_hint": "",
            "size": "150",
            "unit": "mm",
        }
        rate = _rate(Category="PIPE", Sub_Category="GI", Class="C")
        score, breakdown = structured_match_score(extracted, rate)
        self.assertLessEqual(score, 55.0)
        self.assertEqual(breakdown.get("thin_identity_cap"), 55.0)


class EmptyInputFillTests(SimpleTestCase):
    def test_analyse_does_not_fill_blanks_from_rate(self):
        product = {
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
            "class": None,
            "size": "150",
            "unit": None,
            "capacity": None,
        }
        rate = _rate(Class="0", Unit="mm", Capacity="PN16")
        aligned = align_product_taxonomy_from_rate(
            product, rate, overwrite_core_fields=False, fill_blanks=False
        )
        self.assertEqual(aligned.get("category"), "VALVE")
        self.assertEqual(aligned.get("size"), "150")
        self.assertIn(aligned.get("class"), (None, ""))
        self.assertIn(aligned.get("unit"), (None, ""))
        self.assertIn(aligned.get("capacity"), (None, ""))

    def test_select_overwrites_from_rate(self):
        product = {"category": "VALVE", "size": "100"}
        rate = _rate(Category="VALVE", Sub_Category="SLUICE VALVE", Size="150", Unit="mm")
        filled = fill_product_core_fields_from_rate(product, rate, overwrite=True)
        self.assertEqual(str(filled.get("size")), "150")
        self.assertEqual(filled.get("unit"), "mm")

    def test_attributes_leave_unfound_empty(self):
        attrs = _schema_attributes_from_rate(
            schema_keys=["IS", "PN", "Type"],
            rate_attrs={"IS": "14846", "PN": "16", "Type": "rising stem"},
            existing_attrs={"IS": "14846"},
            prefer_rate=False,
            fill_blanks_from_rate=False,
        )
        self.assertEqual(attrs.get("IS"), "14846")
        self.assertNotIn("PN", attrs)
        self.assertNotIn("Type", attrs)


class RematchRecallTests(SimpleTestCase):
    def test_append_prefers_short_slot_support(self):
        hint = "sluice valve 150 mm dia"
        polluted = (
            "EXTERNAL HYDRANT SYSTEM INCLUDING GI PIPES AND FITTINGS "
            "as per specification a) 150 mm dia sluice valve"
        )
        out = _append_section_to_recall_hint(
            hint=hint,
            section_text=polluted,
            sub_category="SLUICE VALVE",
            prefer_slot=True,
        )
        self.assertTrue(out.startswith(hint))
        self.assertLessEqual(len(out), len(hint) + 1 + 180)

    def test_rematch_uses_slot_not_full_section(self):
        mixin = ProductAICandidatesMixin()
        mixin.database_version_id = 1
        mixin._matcher = MagicMock()
        product = {
            "description_hint": "sluice valve 150 mm dia class 0",
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
            "class": "0",
            "size": "150",
            "unit": "mm",
            "_boq_row": {
                "description": (
                    "Providing and fixing GI pipes and fittings for external "
                    "hydrant including sluice valves complete"
                ),
                "slot_description": "a) 150 mm dia sluice valve",
            },
        }
        recall = mixin._product_for_recall(product, refine=True)
        hint = str(recall.get("description_hint") or "")
        self.assertIn("sluice valve", hint.lower())
        self.assertNotIn("gi pipes and fittings", hint.lower())
        self.assertIn("150 mm dia sluice valve", hint.lower())
