"""Tests for BOQ upload, parsing and ownership."""

import io
import tempfile
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.costing.models import RateDetail
from apps.make_list.models import MakeListEntry
from apps.matching.models import ProductMatch
from common.choices import BOQStatus, RunStatus

from apps.boq.models import BOQ, BOQItem
from apps.boq.forms import BOQUploadForm
from apps.boq.services.boq_service import BOQCreationService
from apps.boq.services.make_list_service import BOQMakeListUploadService
from apps.boq.services.parser import parse_boq_items, parse_make_list

User = get_user_model()


def build_boq_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["S. No.", "Description", "Quantity", "Unit"])
    ws.append([None, "150 NB MS Pipe", 100, "m"])
    ws.append([None, "Gate Valve 150mm", 4, "nos"])
    ws.append([None, None, None, None])  # blank row, must be skipped
    ws.append([None, "Sprinkler head", 250, "nos"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_make_workbook(entries=None) -> bytes:
    entries = entries or [("TATA", "Pipes"), ("Zoloto", "Valves"), ("TATA", "Pipes")]
    wb = Workbook()
    ws = wb.active
    ws.title = "Makes"
    ws.append(["Make", "Category"])
    for make, category in entries:
        ws.append([make, category])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_messy_make_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Approved Makes"
    ws.append(["Project Tower A make list"])
    ws.append(["Materials", "Approved Makes", "Brand 2", "OEM"])
    ws.append(["Pipes", "TATA / Jindal; APL", None, None])
    ws.append(["Valves", None, "Zoloto", "Victaulic"])
    ws.append(["Pipes", "TATA", None, None])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_merged_make_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Rate Analysis"
    ws.append(["S.No", "Description", "15mm Dia"])
    ws.append([1, "Not a make list", 100])
    ws2 = wb.create_sheet(title="MAKE LIST")
    ws2.merge_cells("A1:F1")
    ws2["A1"] = "LIST OF ACCEPTABLE MAKE OF MATERIALS"
    ws2.append([None, None, None, None, None, None])
    ws2.append(["S. No.", "Description", "Approved Makes", None, None, None])
    ws2.append([1, "M.S Pipes", "TATA", "JINDALHISSAR", "SURYA ROSHNI", None])
    ws2.append([2, "Forged Steel Fittings", "SS", "MEC (JAINSONS)", "VS", None])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_repeated_make_category_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "PHE MAKELIST"
    ws.merge_cells("A1:C1")
    ws["A1"] = "APPROVED MAKES OF EQUIPMENT & MATERIALS"
    ws.append(["S. No.", "Material", "Make/Manufacturers Name"])
    ws.append([None, "Pipes and Fittings", None])
    ws.append([1, "Vitreous China Sanitaryware", "Jaquar/Kohler /Euronics"])
    ws.append([2, "Concealed Cistern", "Kohler/Euronics"])
    ws.append([3, "Automatic Hand Dryer", "Euronics/Utec/Kohler"])
    ws.append([4, "G.I. Pipes", "Tata/Jindal, Hissar"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_section_serial_boq_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["S.No", "Description", "Unit", "Qty"])
    ws.append([21.0, "Fire pump room works", None, None])
    ws.append([21.1, "Main pump set", "Each", 1])
    ws.append([30.0, "Hydrant system", None, None])
    ws.append([30.1, "Landing valve", "nos", 2])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_titled_boq_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["Project ABC Fire Fighting BOQ"])
    ws.append(["Tender Ref", "ABC-001"])
    ws.append(["Sr. No.", "Particulars", "Qty.", "UOM"])
    ws.append([None, None, "(Rs.)", "(Rs.)"])
    ws.append([27.1 + 0.1, "Hydrant valve", 2.0, "nos"])
    ws.append([None, "Nested row without serial", None, None])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_abbreviated_boq_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["SNo", "Item Desc", "QTY", "ut", "Ignored Column"])
    ws.append(["A-1", "Landing valve", 5, "nos", "Do not show"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_child_quantity_boq_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["S.No", "Description", "Unit", "Qty", "Rate", "Amount"])
    ws.append([1.1, "External hydrant pipework", None, None, None, None])
    ws.append(
        [None, "Material: G.I. pipe conforming to IS:1239", None, None, None, None]
    )
    ws.append([None, "a) 150 mm dia Heavy Class", "M", 175, None, 0])
    ws.append([None, "b) 100 mm dia Heavy Class", "M", 10, None, 0])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_serial_spec_child_boq_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["S.No", "Description", "Unit", "Qty", "Rate", "Amount"])
    ws.append(
        [
            12,
            "Electric driven terrace pump consisting of following",
            None,
            None,
            None,
            None,
        ]
    )
    ws.append(["(a)", "Horizontal multistage centrifugal pump", None, None, None, None])
    ws.append(["(b)", "TEFC motor suitable for 415 volts", None, None, None, None])
    ws.append([12.1, "900 lpm at 35 m Head", "Each", 1, None, None])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def boq_upload(name="boq.xlsx"):
    return SimpleUploadedFile(
        name,
        build_boq_workbook(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def make_upload(name="makes.xlsx"):
    return SimpleUploadedFile(
        name,
        build_make_workbook(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def custom_make_upload(name, entries):
    return SimpleUploadedFile(
        name,
        build_make_workbook(entries),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def messy_make_upload(name="messy_makes.xlsx"):
    return SimpleUploadedFile(
        name,
        build_messy_make_workbook(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class ParserTests(TestCase):
    def test_parse_boq_items_preserves_workbook_rows_and_original_data(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_boq_workbook())
        tmp.close()
        items = parse_boq_items(tmp.name)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["row_number"], 2)
        self.assertEqual(items[0]["description"], "150 NB MS Pipe")
        self.assertEqual(str(items[0]["quantity"]), "100")
        self.assertIsNone(items[0]["original_data"]["s_no"])
        self.assertEqual(items[0]["row_json"]["schema"], "boq_row_group_v1")
        self.assertEqual(items[0]["row_json"]["excel_row_numbers"], [2])
        self.assertEqual(items[2]["row_number"], 5)

    def test_parse_boq_items_preserves_float_section_serial_numbers(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_section_serial_boq_workbook())
        tmp.close()
        items = parse_boq_items(tmp.name)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["row_json"]["rows"][0]["serial_number"], "21.0")
        self.assertEqual(items[0]["original_data"]["s_no"], "21.1")
        self.assertEqual(items[1]["row_json"]["rows"][0]["serial_number"], "30.0")
        self.assertEqual(items[1]["original_data"]["s_no"], "30.1")

    def test_parse_boq_items_detects_later_header_and_cleans_serial_numbers(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_titled_boq_workbook())
        tmp.close()
        items = parse_boq_items(tmp.name)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["row_number"], 5)
        self.assertEqual(
            items[0]["description"], "Hydrant valve\nNested row without serial"
        )
        self.assertEqual(str(items[0]["quantity"]), "2")
        self.assertEqual(items[0]["unit"], "nos")
        self.assertEqual(items[0]["original_data"]["s_no"], "27.2")
        self.assertEqual(items[0]["row_json"]["serial_number"], "27.2")
        self.assertEqual(items[0]["row_json"]["excel_row_numbers"], [5, 6])
        self.assertEqual(len(items[0]["row_json"]["rows"]), 2)
        self.assertIsNone(items[0]["row_json"]["rows"][1]["serial_number"])
        self.assertEqual(
            items[0]["row_json"]["rows"][1]["description"], "Nested row without serial"
        )

    def test_parse_boq_items_maps_aliases_to_static_fields(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_abbreviated_boq_workbook())
        tmp.close()
        items = parse_boq_items(tmp.name)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["description"], "Landing valve")
        self.assertEqual(str(items[0]["quantity"]), "5")
        self.assertEqual(items[0]["unit"], "nos")
        self.assertEqual(
            items[0]["original_data"],
            {
                "s_no": "A-1",
                "description": "Landing valve",
                "unit": "nos",
                "quantity": 5,
            },
        )
        self.assertEqual(items[0]["row_json"]["serial_number"], "A-1")

    def test_parse_boq_items_creates_items_for_child_rows_with_quantities(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_child_quantity_boq_workbook())
        tmp.close()

        items = parse_boq_items(tmp.name)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["row_number"], 4)
        self.assertEqual(items[0]["unit"], "M")
        self.assertEqual(str(items[0]["quantity"]), "175")
        self.assertEqual(items[0]["row_json"]["primary_excel_row_number"], 4)
        self.assertEqual(items[0]["row_json"]["excel_row_numbers"], [2, 3, 4])
        self.assertIn("External hydrant pipework", items[0]["description"])
        self.assertIn("Material: G.I. pipe", items[0]["description"])
        self.assertIn("a) 150 mm dia Heavy Class", items[0]["description"])
        self.assertEqual(items[1]["row_number"], 5)
        self.assertEqual(str(items[1]["quantity"]), "10")
        self.assertIn("b) 100 mm dia Heavy Class", items[1]["description"])

    def test_parse_boq_items_uses_serial_spec_rows_as_child_context(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_serial_spec_child_boq_workbook())
        tmp.close()

        items = parse_boq_items(tmp.name)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["row_number"], 5)
        self.assertEqual(items[0]["unit"], "Each")
        self.assertEqual(str(items[0]["quantity"]), "1")
        self.assertEqual(items[0]["row_json"]["excel_row_numbers"], [2, 3, 4, 5])
        self.assertIn("Electric driven terrace pump", items[0]["description"])
        self.assertIn("Horizontal multistage centrifugal pump", items[0]["description"])
        self.assertIn("TEFC motor", items[0]["description"])
        self.assertIn("900 lpm at 35 m Head", items[0]["description"])

    def test_parse_make_list_pdf_accepts_ai_makes_object(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4 test")
        with (
            self.settings(OPENAI_API_KEY="sk-test"),
            patch("pypdf.PdfReader") as reader_mock,
            patch("ai.service.AIService.is_enabled", return_value=True),
            patch(
                "ai.service.AIService.run_json_prompt",
                return_value={"makes": [{"make": "TATA", "category": "Pipes"}]},
            ),
        ):
            reader_mock.return_value.pages = [
                Mock(extract_text=lambda: "Approved makes TATA")
            ]
            self.assertEqual(
                parse_make_list(tmp.name), [{"make": "TATA", "category": "Pipes"}]
            )

    def test_parse_make_list_detects_later_headers_aliases_and_multi_make_cells(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_messy_make_workbook())
        tmp.close()

        entries = parse_make_list(tmp.name)

        self.assertEqual(
            entries,
            [
                {"make": "TATA", "category": "Pipes"},
                {"make": "Jindal", "category": "Pipes"},
                {"make": "APL", "category": "Pipes"},
                {"make": "Zoloto", "category": "Valves"},
                {"make": "Victaulic", "category": "Valves"},
            ],
        )

    def test_parse_make_list_scans_sheets_and_merged_make_columns(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_merged_make_workbook())
        tmp.close()

        entries = parse_make_list(tmp.name)

        self.assertEqual(
            entries[:6],
            [
                {"make": "TATA", "category": "M.S Pipes"},
                {"make": "JINDALHISSAR", "category": "M.S Pipes"},
                {"make": "SURYA ROSHNI", "category": "M.S Pipes"},
                {"make": "SS", "category": "Forged Steel Fittings"},
                {"make": "MEC (JAINSONS)", "category": "Forged Steel Fittings"},
                {"make": "VS", "category": "Forged Steel Fittings"},
            ],
        )

    def test_parse_make_list_keeps_same_make_for_different_materials(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(build_repeated_make_category_workbook())
        tmp.close()

        entries = parse_make_list(tmp.name)

        self.assertIn(
            {"make": "Kohler", "category": "Vitreous China Sanitaryware"}, entries
        )
        self.assertIn({"make": "Kohler", "category": "Concealed Cistern"}, entries)
        self.assertIn({"make": "Kohler", "category": "Automatic Hand Dryer"}, entries)
        self.assertIn({"make": "Euronics", "category": "Concealed Cistern"}, entries)
        self.assertIn({"make": "Euronics", "category": "Automatic Hand Dryer"}, entries)
        self.assertIn({"make": "Jindal, Hissar", "category": "G.I. Pipes"}, entries)


class BOQUploadFormTests(TestCase):
    def test_make_list_accepts_pdf_but_boq_requires_excel(self):
        form = BOQUploadForm(
            data={"boq_name": "Tower A"},
            files={
                "uploaded_file": boq_upload(),
                "make_list_file": SimpleUploadedFile(
                    "makes.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
            },
        )
        self.assertTrue(form.is_valid(), form.errors)

        invalid = BOQUploadForm(
            data={"boq_name": "Tower A"},
            files={"uploaded_file": SimpleUploadedFile("boq.pdf", b"%PDF-1.4")},
        )
        self.assertFalse(invalid.is_valid())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BOQCreationServiceTests(TestCase):
    def setUp(self):
        self.expert = User.objects.create_user("expert@example.com", "pass12345")

    def test_creates_boq_run_items_and_makes(self):
        boq = BOQCreationService(
            user=self.expert,
            boq_name="Tower A",
            uploaded_file=boq_upload(),
            make_list_file=make_upload(),
        ).run()
        self.assertEqual(boq.status, BOQStatus.UPLOADED)
        self.assertEqual(boq.user, self.expert)
        run = boq.runs.get(run_number=1)
        self.assertEqual(run.status, RunStatus.QUEUED)
        self.assertEqual(run.original_headers[0]["label"], "S No")
        self.assertEqual(BOQItem.objects.filter(boq_run=run).count(), 3)
        self.assertEqual(MakeListEntry.objects.filter(boq_run=run).count(), 2)

    def test_make_list_optional(self):
        boq = BOQCreationService(
            user=self.expert, boq_name="No Makes", uploaded_file=boq_upload()
        ).run()
        run = boq.runs.get(run_number=1)
        self.assertEqual(BOQItem.objects.filter(boq_run=run).count(), 3)
        self.assertEqual(MakeListEntry.objects.filter(boq_run=run).count(), 0)

    def test_make_list_update_is_scoped_to_one_boq_latest_run(self):
        first = BOQCreationService(
            user=self.expert,
            boq_name="First",
            uploaded_file=boq_upload("first.xlsx"),
            make_list_file=make_upload("first_makes.xlsx"),
        ).run()
        second = BOQCreationService(
            user=self.expert,
            boq_name="Second",
            uploaded_file=boq_upload("second.xlsx"),
            make_list_file=custom_make_upload(
                "old_second_makes.xlsx", [("OldMake", "Old")]
            ),
        ).run()
        self.assertEqual(second.runs.latest("run_number").make_list_entries.count(), 1)

        count = BOQMakeListUploadService(
            boq=second,
            make_list_file=custom_make_upload(
                "second_makes.xlsx", [("Victaulic", "Pipes")]
            ),
        ).run()

        self.assertEqual(count, 1)
        self.assertEqual(first.runs.latest("run_number").make_list_entries.count(), 2)
        self.assertEqual(second.runs.latest("run_number").make_list_entries.count(), 1)
        self.assertEqual(
            set(
                first.runs.latest("run_number").make_list_entries.values_list(
                    "make", flat=True
                )
            ),
            {"TATA", "Zoloto"},
        )
        self.assertEqual(
            set(
                second.runs.latest("run_number").make_list_entries.values_list(
                    "make", flat=True
                )
            ),
            {"Victaulic"},
        )

    def test_same_name_boqs_with_same_make_list_filename_stay_isolated(self):
        first = BOQCreationService(
            user=self.expert,
            boq_name="Tower A",
            uploaded_file=boq_upload("tower_a_1.xlsx"),
            make_list_file=make_upload("same_makes.xlsx"),
        ).run()
        second = BOQCreationService(
            user=self.expert,
            boq_name="Tower A",
            uploaded_file=boq_upload("tower_a_2.xlsx"),
            make_list_file=make_upload("same_makes.xlsx"),
        ).run()

        self.assertNotEqual(first.pk, second.pk)
        first_run = first.runs.latest("run_number")
        second_run = second.runs.latest("run_number")
        self.assertNotEqual(first_run.pk, second_run.pk)
        self.assertEqual(first_run.make_list_entries.count(), 2)
        self.assertEqual(second_run.make_list_entries.count(), 2)

        BOQMakeListUploadService(
            boq=first,
            make_list_file=custom_make_upload(
                "same_makes.xlsx", [("Victaulic", "Valves")]
            ),
        ).run()

        self.assertEqual(
            set(first_run.make_list_entries.values_list("make", flat=True)),
            {"Victaulic"},
        )
        self.assertEqual(
            set(second_run.make_list_entries.values_list("make", flat=True)),
            {"TATA", "Zoloto"},
        )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BOQOwnershipTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin@example.com", "pass12345")
        self.alice = User.objects.create_user("alice@example.com", "pass12345")
        self.bob = User.objects.create_user("bob@example.com", "pass12345")
        self.alice_boq = BOQCreationService(self.alice, "Alice BOQ", boq_upload()).run()

    def test_detail_shows_section_serial_rows_from_grouped_items(self):
        boq = BOQCreationService(
            user=self.alice,
            boq_name="Section BOQ",
            uploaded_file=SimpleUploadedFile(
                "section_boq.xlsx",
                build_section_serial_boq_workbook(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ).run()

        self.client.force_login(self.alice)
        response = self.client.get(reverse("boq:detail", args=[boq.pk]))

        self.assertContains(response, "21.0")
        self.assertContains(response, "30.0")
        self.assertContains(response, "Fire pump room works")
        self.assertContains(response, "Hydrant system")

    def test_expert_sees_only_own_boqs(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("boq:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Alice BOQ")

    def test_owner_sees_own_boq(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("boq:list"))
        self.assertContains(response, "Alice BOQ")

    def test_other_expert_cannot_open_boq(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("boq:detail", args=[self.alice_boq.pk]))
        self.assertEqual(response.status_code, 404)

    def test_super_admin_can_open_any_boq(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("boq:detail", args=[self.alice_boq.pk]))
        self.assertEqual(response.status_code, 200)

    def test_upload_view_creates_boq(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("boq:upload"),
            {
                "boq_name": "Bob BOQ",
                "uploaded_file": boq_upload(),
                "make_list_file": make_upload(),
            },
        )
        boq = BOQ.objects.get(boq_name="Bob BOQ")
        self.assertRedirects(response, reverse("boq:detail", args=[boq.pk]))
        self.assertEqual(boq.user, self.bob)

    def test_owner_can_upload_make_list_for_own_boq(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("boq:make_list_upload", args=[self.alice_boq.pk]),
            {"make_list_file": make_upload("alice_makes.xlsx")},
        )
        self.assertRedirects(
            response, reverse("boq:make_list", args=[self.alice_boq.pk])
        )
        run = self.alice_boq.runs.latest("run_number")
        self.assertEqual(run.make_list_entries.count(), 2)

    def test_detail_shows_all_boq_items_without_make_list_upload_card_or_pagination(
        self,
    ):
        run = self.alice_boq.runs.latest("run_number")
        run.original_headers = [{"key": "ignored", "label": "Ignored Column"}]
        run.save(update_fields=["original_headers"])
        BOQItem.objects.bulk_create(
            [
                BOQItem(
                    boq_run=run,
                    row_number=row_number,
                    description=f"Extra item {row_number}",
                    original_data={
                        "s_no": None,
                        "description": f"Extra item {row_number}",
                        "quantity": 1,
                        "unit": "nos",
                    },
                )
                for row_number in range(6, 18)
            ]
        )

        self.client.force_login(self.alice)
        response = self.client.get(reverse("boq:detail", args=[self.alice_boq.pk]))

        self.assertContains(response, "Extra item 17")
        self.assertContains(response, "S No")
        self.assertContains(response, "Description")
        self.assertContains(response, "Unit")
        self.assertContains(response, "Quantity")
        self.assertNotContains(response, "Ignored Column")
        self.assertNotContains(response, "Make list upload")
        self.assertNotContains(response, "Upload make list")
        self.assertNotContains(response, "Page 1")

    def test_detail_hides_calculated_prices_while_run_is_processing(self):
        run = self.alice_boq.runs.latest("run_number")
        item = run.items.first()
        match = ProductMatch.objects.create(
            boq_item=item,
            confidence_score=95,
            match_reason="exact",
        )
        RateDetail.objects.create(product_match=match, rate_contribution="123.45")
        run.status = RunStatus.PROCESSING
        run.save(update_fields=["status"])
        self.alice_boq.status = BOQStatus.PROCESSING
        self.alice_boq.save(update_fields=["status"])

        self.client.force_login(self.alice)
        response = self.client.get(reverse("boq:detail", args=[self.alice_boq.pk]))

        self.assertIsNone(response.context["item_rows"][0]["final_rate"])
        self.assertNotContains(response, "123.45")

    def test_detail_shows_calculated_prices_after_run_completes(self):
        run = self.alice_boq.runs.latest("run_number")
        item = run.items.first()
        match = ProductMatch.objects.create(
            boq_item=item,
            confidence_score=95,
            match_reason="exact",
        )
        RateDetail.objects.create(product_match=match, rate_contribution="123.45")
        run.status = RunStatus.COMPLETED
        run.save(update_fields=["status"])
        self.alice_boq.status = BOQStatus.UNDER_REVIEW
        self.alice_boq.save(update_fields=["status"])

        self.client.force_login(self.alice)
        response = self.client.get(reverse("boq:detail", args=[self.alice_boq.pk]))

        self.assertEqual(str(response.context["item_rows"][0]["final_rate"]), "123.45")
        self.assertContains(response, "123.45")

    def test_make_list_page_shows_current_file_and_replace_action(self):
        self.client.force_login(self.alice)
        self.client.post(
            reverse("boq:make_list_upload", args=[self.alice_boq.pk]),
            {"make_list_file": make_upload("alice_makes.xlsx")},
        )

        response = self.client.get(reverse("boq:make_list", args=[self.alice_boq.pk]))

        self.assertContains(response, "Current file:")
        self.assertContains(response, "alice_makes")
        self.assertContains(response, "Replace make list")
        self.assertNotContains(response, "Upload Make List")

    def test_make_list_page_shows_all_entries_without_pagination(self):
        run = self.alice_boq.runs.latest("run_number")
        MakeListEntry.objects.bulk_create(
            [
                MakeListEntry(boq_run=run, make=f"Make {number:02d}", category="Pipes")
                for number in range(1, 16)
            ]
        )

        self.client.force_login(self.alice)
        response = self.client.get(reverse("boq:make_list", args=[self.alice_boq.pk]))

        self.assertContains(response, "Make 15")
        self.assertNotContains(response, "Page 1")
        self.assertNotContains(response, "Next")
        self.assertEqual(response.context["total_makes"], 15)

    def test_other_expert_cannot_upload_make_list_for_boq(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("boq:make_list_upload", args=[self.alice_boq.pk]),
            {"make_list_file": make_upload("bob_makes.xlsx")},
        )
        self.assertEqual(response.status_code, 404)
        run = self.alice_boq.runs.latest("run_number")
        self.assertEqual(run.make_list_entries.count(), 0)
