from django.test import SimpleTestCase

from utils.product_synonyms import (
    format_synonym_map_for_ai,
    format_synonym_rules_for_ai,
)


class SynonymRulesForAiTests(SimpleTestCase):
    def test_rules_are_short_and_include_materials(self):
        rules = format_synonym_rules_for_ai()
        self.assertLess(len(rules), 1500)
        self.assertIn("GI", rules)
        self.assertIn("galvanized", rules.lower())
        self.assertIn("Meaning-first", rules)
        # Full product phrase catalog must not appear in prompt rules.
        self.assertNotIn("ACCESSORIES > ROSETTEE PLATE:", rules)
        self.assertNotIn("Product synonyms (Category > Sub-category:", rules)

    def test_full_map_still_available_for_code_debug(self):
        full = format_synonym_map_for_ai()
        self.assertGreater(len(full), len(format_synonym_rules_for_ai()))
        self.assertIn("Product synonyms (Category > Sub-category:", full)

    def test_prompt_templates_use_synonym_rules_placeholder(self):
        from pathlib import Path

        prompts = Path(__file__).resolve().parents[2] / "backend" / "ai" / "prompts"
        for name in (
            "extract_products.txt",
            "map_product_match.txt",
            "map_make_list_categories.txt",
        ):
            text = (prompts / name).read_text(encoding="utf-8")
            self.assertIn("{{SYNONYM_RULES}}", text, msg=name)
            self.assertNotIn("{{SYNONYM_MAP}}", text, msg=name)
