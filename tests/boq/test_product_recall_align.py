"""First Analyse recall should align with product Re-analyse."""
from django.test import SimpleTestCase

from apps.boq.services.product_ai_candidates import ProductAICandidatesMixin


class _RecallStub(ProductAICandidatesMixin):
    database_version_id = 1
    _matcher = None  # type: ignore[assignment]


class ProductRecallAlignTests(SimpleTestCase):
    def setUp(self):
        self.recall = _RecallStub()

    def test_initial_analyse_drops_category_sub_when_hint_has_identity(self):
        product = {
            "description_hint": "Cast iron non-return valve (VALVE / NON RETURN VALVE), 200 mm",
            "category": "PIPE",
            "sub_category": "MS",
            "size": "200",
            "_boq_row": {
                "description": "Supply reflux type check valve 200 mm dia for hydrant system",
                "slot_description": "200 mm dia",
            },
        }
        result = self.recall._product_for_recall(product, refine=False)
        self.assertTrue(result.get("_hint_first_recall"))
        self.assertIsNone(result.get("category"))
        self.assertIsNone(result.get("sub_category"))
        hint = str(result.get("description_hint") or "")
        self.assertIn("non-return valve", hint.lower())
        self.assertIn("hydrant system", hint.lower())

    def test_reanalyse_hint_path_unchanged(self):
        product = {
            "description_hint": "butterfly valve 150 mm",
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
            "_boq_row": {"description": "Supply butterfly valve 150mm"},
        }
        result = self.recall._product_for_recall(product, refine=True)
        self.assertTrue(result.get("_hint_first_recall"))
        self.assertIsNone(result.get("category"))
        self.assertIsNone(result.get("sub_category"))
        self.assertIn("butterfly valve", str(result.get("description_hint") or "").lower())

    def test_reanalyse_keeps_sub_when_hint_agrees_fire_hose_box(self):
        product = {
            "description_hint": "class MS fire hose box (hydrant), capacity 30X24X10",
            "category": "HYDRANT",
            "sub_category": "FIRE HOSE BOX",
            "class": "MS",
            "capacity": "30X24X10",
            "_boq_row": {
                "description": (
                    "Providing and fixing external fire hose box, wall mounting, "
                    "to accommodate two 15m length of delivery hoses and branch pipes"
                ),
            },
        }
        result = self.recall._product_for_recall(product, refine=True)
        self.assertEqual(result.get("sub_category"), "FIRE HOSE BOX")
        self.assertEqual(result.get("category"), "HYDRANT")
        hint = str(result.get("description_hint") or "").lower()
        self.assertIn("fire hose box", hint)
        self.assertNotIn("branch pipe", hint)
        self.assertNotIn("15m", hint)
