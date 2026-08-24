from django.test import SimpleTestCase

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
