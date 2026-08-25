from django.test import SimpleTestCase

from apps.boq.services.boq_extraction_groups import _compact_anchor_payload, _iter_extract_batches
from apps.boq.services.boq_extraction_slots import (
    _enrich_description_hint,
    _share_section_attributes,
    _snap_identity_from_product_context,
)
from apps.boq.services.boq_row_grouping_service import grouped_anchor_rows


def _row(row_id, serial, parent, description, qty=None, unit=None, depth=0):
    values = {"description": description, "qty": qty, "unit": unit}
    return {
        "row_id": row_id,
        "serial": serial,
        "parent_row_id": parent,
        "depth": depth,
        "values": values,
        "display_values": values,
    }


class ChapterResidualOrderTests(SimpleTestCase):
    def test_chapter_products_before_dotted_packages_keep_sheet_order(self):
        """BOQ_4 shape: pipes c)–j) under chapter 1 appear before 1.1 on Analysis."""
        rows = [
            _row("r1", "1", None, "SPRINKLER SYSTEM", depth=0),
        ]
        letters = ["c", "d", "e", "f", "g", "h", "i", "j"]
        for index, letter in enumerate(letters, start=2):
            rows.append(
                _row(
                    f"r{index}",
                    f"{letter})",
                    "r1",
                    f"{letter}) {150 - index * 10} mm dia pipe",
                    qty=10 + index,
                    unit="M",
                    depth=1,
                )
            )
        rows.extend(
            [
                _row("r10", "1.1", "r1", "Sprinkler heads", depth=1),
                _row("r11", "a)", "r10", "Pendent sprinklers 15 mm", depth=2),
                _row("r12", "", "r11", "i) Operating Temp. : 68 deg.C.", qty=120, unit="No.", depth=3),
                _row("r13", "", "r11", "ii) Operating Temp. : 79 deg.C.", qty=10, unit="No.", depth=3),
                _row("r14", "", "r11", "iii) Operating Temp. : 141 deg.C.", qty=20, unit="No.", depth=3),
            ]
        )

        groups = grouped_anchor_rows({"rows": rows})
        serials = [str(group.get("serial") or "") for group in groups]
        self.assertGreaterEqual(len(groups), 2)
        self.assertEqual(serials[0], "1")
        self.assertEqual(serials[1], "1.1")
        self.assertEqual(groups[0]["slot_count"], 8)
        self.assertEqual(groups[1]["slot_count"], 3)
        self.assertEqual(
            [slot["serial"] for slot in groups[0]["slots"]],
            ["c)", "d)", "e)", "f)", "g)", "h)", "i)", "j)"],
        )


class SlotProductContextTests(SimpleTestCase):
    def test_size_only_slots_get_owning_sluice_valve_context(self):
        rows = [
            _row("r1", "1", None, "HYDRANT SYSTEM", depth=0),
            _row(
                "r2",
                "1.3",
                "r1",
                "Providing and fixing Cast Iron sluice valve with hand wheel "
                "(as per IS:14846)",
                depth=1,
            ),
            _row("r3", "a)", "r2", "a) 250 mm dia", qty=2, unit="Each", depth=2),
            _row("r4", "b)", "r2", "b) 200 mm dia", qty=4, unit="Each", depth=2),
            _row("r5", "c)", "r2", "c) 150 mm dia", qty=6, unit="Each", depth=2),
        ]
        groups = grouped_anchor_rows({"rows": rows})
        self.assertTrue(groups)
        package = groups[0]
        self.assertEqual(package["slot_count"], 3)
        for slot in package["slots"]:
            context = str(slot.get("product_context") or "")
            self.assertIn("sluice valve", context.lower())
            self.assertNotIn("HYDRANT SYSTEM", context)

    def test_compact_payload_includes_product_context(self):
        rows = [
            _row("r1", "1", None, "HYDRANT SYSTEM", depth=0),
            _row(
                "r2",
                "1.1",
                "r1",
                "Providing pipework for External Hydrant System",
                depth=1,
            ),
            _row("r3", "", "r2", "Material: G.I. pipe conforming to IS:1239", depth=2),
            _row("r4", "a)", "r2", "a) 150 mm dia (Heavy Class)", qty=175, unit="M", depth=2),
        ]
        groups = grouped_anchor_rows({"rows": rows})
        self.assertTrue(groups)
        package = groups[0]
        payload = _compact_anchor_payload(package)
        self.assertTrue(payload["slots"][0].get("product_context"))
        self.assertIn("pipe", payload["slots"][0]["product_context"].lower())


class ExtractIdentityRepairTests(SimpleTestCase):
    def test_snap_overrides_wrong_pipe_with_sluice_from_context(self):
        product = {
            "category": "PIPE",
            "sub_category": "GI",
            "size": "250",
            "description_hint": "sluice valve, 250 mm dia",
        }
        snapped = _snap_identity_from_product_context(
            product,
            product_context=(
                "Providing and fixing Cast Iron sluice valve with hand wheel"
            ),
            taxonomy={
                "categories": ["PIPE", "VALVE", "HYDRANT"],
                "sub_categories_by_category": {
                    "PIPE": ["GI", "MS"],
                    "VALVE": ["SLUICE VALVE", "BUTTERFLY"],
                    "HYDRANT": ["LANDING VALVE"],
                },
                "classes_by_category_sub_category": {},
                "classes": [],
            },
        )
        self.assertEqual(snapped["category"], "VALVE")
        self.assertEqual(snapped["sub_category"], "SLUICE VALVE")

    def test_keep_good_ai_description_hint(self):
        hint = _enrich_description_hint(
            {
                "description_hint": "cast iron sluice valve, 250 mm dia, IS 14846",
                "category": "VALVE",
                "sub_category": "SLUICE VALVE",
                "size": "250",
                "unit": "mm",
            },
            section_text="HYDRANT SYSTEM",
            slot_desc="a) 250 mm dia",
            product_context="Providing and fixing Cast Iron sluice valve",
        )
        self.assertIn("sluice", hint.lower())
        self.assertIn("250", hint)

    def test_pipework_not_sprinkler_in_ai_description(self):
        hint = _enrich_description_hint(
            {
                "description_hint": "65mm dia SPRINKLER",
                "category": "PIPE",
                "sub_category": "MS",
                "class": "C",
                "size": "65",
                "unit": "mm",
            },
            section_text="3 SPRINKLER SYSTEM",
            slot_desc="g) 65 mm dia pipe",
            product_context=(
                "Providing, laying pipework for Sprinkler System. "
                "Material: G.I. pipe Class C. g) 65 mm dia pipe"
            ),
        )
        self.assertIn("pipe", hint.lower())
        self.assertIn("65", hint)
        self.assertIn("ms", hint.lower())
        self.assertNotRegex(hint.lower(), r"^65\s*mm\s*dia\s*sprinkler$")

    def test_size_only_hint_gets_taxonomy_identity(self):
        hint = _enrich_description_hint(
            {
                "description_hint": "200mm",
                "category": "PIPE",
                "sub_category": "GI",
                "class": "C",
                "size": "200",
                "unit": "mm",
            },
            section_text="HYDRANT SYSTEM",
            slot_desc="b) 200 mm dia",
            product_context="Material: G.I. pipe conforming to IS:1239 Heavy Class",
        )
        self.assertIn("gi", hint.lower())
        self.assertIn("pipe", hint.lower())
        self.assertIn("200", hint)
        self.assertNotEqual(hint.strip().lower(), "200mm")

    def test_expand_short_hint_from_product_context(self):
        hint = _enrich_description_hint(
            {
                "description_hint": "sluice valve, 250 mm dia",
                "category": "VALVE",
                "sub_category": "SLUICE VALVE",
                "size": "250",
                "unit": "mm",
            },
            section_text="HYDRANT SYSTEM",
            slot_desc="a) 250 mm dia",
            product_context=(
                "Providing and fixing Cast Iron sluice valve with hand wheel, "
                "having rising stem (OS & Y Type) complete with bolts, nuts "
                "(as per IS:14846)"
            ),
        )
        self.assertIn("sluice", hint.lower())
        self.assertIn("250", hint)
        self.assertNotIn("providing and fixing", hint.lower())

    def test_snap_pipework_external_hydrant_to_pipe_gi(self):
        snapped = _snap_identity_from_product_context(
            {
                "category": "PIPE",
                "sub_category": "EXTERNAL HYDRANT",
                "class": "",
                "description_hint": "class C external hydrant (pipe), 150 mm dia",
            },
            product_context=(
                "Providing pipework for External Hydrant System. "
                "Material: G.I. pipe conforming to IS:1239 Heavy Class. "
                "a) 150 mm dia (Heavy Class)"
            ),
            taxonomy={
                "categories": ["PIPE", "HYDRANT"],
                "sub_categories_by_category": {
                    "PIPE": ["GI", "MS"],
                    "HYDRANT": ["EXTERNAL HYDRANT", "LANDING VALVE"],
                },
                "classes_by_category_sub_category": {
                    "PIPE": {"GI": ["C"], "MS": ["C"]},
                    "HYDRANT": {"EXTERNAL HYDRANT": ["0"]},
                },
                "classes": ["0", "C"],
            },
        )
        self.assertEqual(snapped["category"], "PIPE")
        self.assertEqual(snapped["sub_category"], "GI")
        self.assertEqual(str(snapped.get("class") or "").upper(), "C")

    def test_snap_heavy_class_to_c(self):
        snapped = _snap_identity_from_product_context(
            {
                "category": "PIPE",
                "sub_category": "GI",
                "class": "",
                "description_hint": "GI pipe heavy class",
            },
            product_context="Providing and fixing G.I. pipes heavy class",
            taxonomy={
                "categories": ["PIPE"],
                "sub_categories_by_category": {"PIPE": ["GI"]},
                "classes_by_category_sub_category": {("PIPE", "GI"): ["A", "B", "C"]},
                "classes": ["A", "B", "C"],
            },
        )
        self.assertEqual(str(snapped.get("class") or "").upper(), "C")

    def test_share_attributes_only_within_same_family(self):
        products = [
            {
                "category": "PIPE",
                "sub_category": "GI",
                "attributes": {"is": "1239"},
            },
            {
                "category": "VALVE",
                "sub_category": "SLUICE VALVE",
                "attributes": {},
            },
            {
                "category": "PIPE",
                "sub_category": "GI",
                "attributes": {},
            },
        ]
        shared = _share_section_attributes(products)
        self.assertEqual(shared[0]["attributes"].get("is"), "1239")
        self.assertEqual(shared[2]["attributes"].get("is"), "1239")
        self.assertFalse(shared[1]["attributes"].get("is"))


class MultiSlotBatchTests(SimpleTestCase):
    def test_multi_slot_sections_batch_alone(self):
        groups = [
            {"row_id": "r1", "slot_count": 3, "slots": [{}, {}, {}], "full_description": "a"},
            {"row_id": "r2", "slot_count": 1, "slots": [{}], "full_description": "b"},
            {"row_id": "r3", "slot_count": 1, "slots": [{}], "full_description": "c"},
        ]
        batches = _iter_extract_batches(groups)
        self.assertEqual(len(batches[0]), 1)
        self.assertEqual(batches[0][0]["row_id"], "r1")
        # Single-slot groups may still pack together.
        single_ids = [g["row_id"] for batch in batches[1:] for g in batch]
        self.assertEqual(single_ids, ["r2", "r3"])
