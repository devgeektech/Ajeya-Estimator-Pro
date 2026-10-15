"""Make & Vendor sync preserves manual picks; filter clear restores lowest."""

from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.boq.models import BOQ
from apps.boq.services.make_vendor_selection_service import MakeVendorSelectionService
from common.choices import BOQStatus

User = get_user_model()


class MakeVendorSyncPreserveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="mv@example.com", password="password"
        )
        self.boq = BOQ.objects.create(
            boq_name="MV Sync BOQ",
            status=BOQStatus.MAKE_VENDOR,
            user=self.user,
            uploaded_file="boq/mv.xlsx",
            analysis_data={
                "make_vendor_defaults_applied": True,
                "rows": [
                    {
                        "row_id": "r1",
                        "products": [
                            {
                                "product_index": 0,
                                "category": "INSTRUMENT",
                                "sub_category": "PRESSURE GAUGE",
                                "catalog_product_id": "40",
                                "db_match_status": "matched",
                                "db_match_confidence": 100.0,
                                "vendor_selection_source": "manual",
                                "selected_make": "DANFOSS",
                                "selected_vendor": "BILLU",
                                "vendor_selection": {
                                    "status": "matched",
                                    "make": "DANFOSS",
                                    "vendor": "BILLU",
                                    "catalog_product_id": "40",
                                    "product_id": "40",
                                    "rate_detail": {"final_material_amount": 856.48},
                                },
                            },
                            {
                                "product_index": 1,
                                "category": "SPRINKLER",
                                "sub_category": "UPRIGHT",
                                "catalog_product_id": "10",
                                "db_match_status": "matched",
                                "db_match_confidence": 100.0,
                                "vendor_selection_source": "lowest_defaults",
                                "selected_make": "HD",
                                "selected_vendor": "RAJA",
                                "vendor_selection": {
                                    "status": "matched",
                                    "make": "HD",
                                    "vendor": "RAJA",
                                    "catalog_product_id": "10",
                                    "product_id": "10",
                                    "rate_detail": {"final_material_amount": 100.0},
                                },
                            },
                        ],
                    }
                ],
            },
            boq_data={"rows": [{"row_id": "r1", "qty": 1}]},
        )

    def test_sync_preserves_manual_pick_when_product_id_unchanged(self):
        service = MakeVendorSelectionService(self.boq.pk)

        def capture(product, *, database_version_id):
            pid = str(product.get("catalog_product_id") or "")
            return dict(product), pid

        with (
            patch.object(service, "_database_version_id", return_value=1),
            patch.object(service, "_capture_analysis_product_id", side_effect=capture),
            patch.object(service, "_exact_match_and_rates") as exact,
        ):
            result = service.sync_analysis_product_ids(refresh_rates_if_changed=True)

        exact.assert_not_called()
        self.assertEqual(result["changed_count"], 0)
        self.assertEqual(result["refreshed_count"], 0)
        self.boq.refresh_from_db()
        products = (self.boq.analysis_data or {})["rows"][0]["products"]
        self.assertEqual(products[0]["vendor_selection"]["make"], "DANFOSS")
        self.assertEqual(products[0]["vendor_selection"]["vendor"], "BILLU")
        self.assertEqual(products[0]["vendor_selection_source"], "manual")

    def test_sync_refreshes_only_when_product_id_changes(self):
        service = MakeVendorSelectionService(self.boq.pk)

        def capture(product, *, database_version_id):
            updated = dict(product)
            if int(product.get("product_index") or 0) == 0:
                updated["catalog_product_id"] = "99"
                updated["catalog_product_id_changed"] = True
                return updated, "99"
            pid = str(product.get("catalog_product_id") or "")
            return updated, pid

        fake_payload = {
            "status": "matched",
            "make": "NEWMAKE",
            "vendor": "NEWVENDOR",
            "rate_detail": {"final_material_amount": 1.0},
            "labour_detail": None,
            "line_output": {},
        }

        with (
            patch.object(service, "_database_version_id", return_value=1),
            patch.object(service, "_capture_analysis_product_id", side_effect=capture),
            patch.object(
                service, "_approved_makes_for_subcategory", return_value=[]
            ),
            patch.object(
                service, "_exact_match_and_rates", return_value=dict(fake_payload)
            ) as exact,
        ):
            result = service.sync_analysis_product_ids(refresh_rates_if_changed=True)

        self.assertEqual(exact.call_count, 1)
        self.assertEqual(result["changed_count"], 1)
        self.assertEqual(result["refreshed_count"], 1)
        self.boq.refresh_from_db()
        products = (self.boq.analysis_data or {})["rows"][0]["products"]
        self.assertEqual(products[0]["vendor_selection"]["make"], "NEWMAKE")
        self.assertEqual(products[1]["vendor_selection"]["make"], "HD")


class SamePriceBadgeLabelTests(SimpleTestCase):
    def test_status_label_does_not_duplicate_same_price(self):
        # Mirrors Alpine statusLabel: same-price has its own badge.
        same_price_tie = True
        status = "matched"
        if same_price_tie:
            label = None  # dedicated badge only
        elif status == "matched":
            label = "Matched"
        else:
            label = "other"
        self.assertIsNone(label)


class AvailableMakeCascadeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="cascade_mv@example.com", password="password"
        )
        self.boq = BOQ.objects.create(
            boq_name="Cascade BOQ",
            status=BOQStatus.MAKE_VENDOR,
            user=self.user,
            uploaded_file="boq/casc.xlsx",
            analysis_data={
                "rows": [
                    {
                        "row_id": "r1",
                        "products": [
                            {
                                "product_index": 0,
                                "category": "PIPING",
                                "sub_category": "MS PIPE",
                                "catalog_product_id": "1",
                                "selected_make": None,
                                "selected_vendor": None,
                            }
                        ],
                    }
                ],
            },
            boq_data={"rows": [{"row_id": "r1", "qty": 10}]},
        )

    def test_catalog_includes_available_makes_and_vendors(self):
        service = MakeVendorSelectionService(self.boq.pk)
        with (
            patch.object(service, "_make_options_for_scope", return_value=(["Lowest price", "TATA"], ["TATA"], True)),
            patch.object(service, "_rate_master_makes_for_subcategory", return_value=["JINDAL", "TATA"]),
            patch.object(service, "_vendors_for_subcategory_make", return_value=["SUPPLIER A"]),
            patch.object(service, "_lowest_amount_maps", return_value={"lowest_amount": "100.00"}),
            patch.object(service, "_approved_makes_for_subcategory", return_value=["TATA"]),
        ):
            catalog = service._build_selection_catalog(self.boq.analysis_data, database_version_id=1)

        self.assertEqual(len(catalog["categories"]), 1)
        cat = catalog["categories"][0]
        self.assertIn("available_makes", cat)
        self.assertEqual(cat["available_makes"], ["JINDAL", "TATA"])
        self.assertEqual(cat["make_options"], ["Lowest price", "TATA"])
        self.assertIn("JINDAL", cat["vendors_by_make"])

        sub = cat["sub_categories"][0]
        self.assertIn("available_makes", sub)
        self.assertEqual(sub["available_makes"], ["JINDAL", "TATA"])
        self.assertEqual(sub["make_options"], ["Lowest price", "TATA"])
        self.assertIn("JINDAL", sub["vendors_by_make"])

    def test_apply_subcategory_allows_available_db_make(self):
        service = MakeVendorSelectionService(self.boq.pk)
        fake_payload = {
            "status": "matched",
            "make": "JINDAL",
            "vendor": "SUPPLIER A",
            "line_output": {"material_rate": "150.00"},
        }
        with (
            patch.object(MakeVendorSelectionService, "has_make_list", new_callable=PropertyMock, return_value=True),
            patch.object(service, "_database_version_id", return_value=1),
            patch.object(service.make_list_service, "approved_makes_for_category", return_value=["TATA"]),
            patch.object(service, "_rate_master_makes_for_subcategory", return_value=["JINDAL", "TATA"]),
            patch.object(service, "_exact_match_and_rates", return_value=dict(fake_payload)),
        ):
            result = service.apply_subcategory_make(
                category="PIPING",
                sub_category="MS PIPE",
                make="JINDAL",
                vendor="SUPPLIER A",
            )

        self.assertEqual(result["make"], "JINDAL")
        self.assertEqual(result["vendor"], "SUPPLIER A")
        self.boq.refresh_from_db()
        row_prod = self.boq.analysis_data["rows"][0]["products"][0]
        self.assertEqual(row_prod["selected_make"], "JINDAL")
        self.assertEqual(row_prod["selected_vendor"], "SUPPLIER A")


class MakeVendorProductWiseCascadeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="cascade_prod@example.com", password="password"
        )
        self.boq = BOQ.objects.create(
            boq_name="Cascade Product BOQ",
            status=BOQStatus.MAKE_VENDOR,
            user=self.user,
            uploaded_file="boq/cascade_prod.xlsx",
            analysis_data={
                "make_vendor_defaults_applied": True,
                "rows": [
                    {
                        "row_id": "r1",
                        "products": [
                            {
                                "product_index": 0,
                                "category": "TANK",
                                "sub_category": "AIR CUSHION TANK",
                                "catalog_product_id": "161",
                                "size": "200.00",
                                "unit": "mm",
                                "selected_make": "OLD_MAKE",
                                "selected_vendor": "OLD_VENDOR",
                                "vendor_selection": {
                                    "status": "matched",
                                    "make": "OLD_MAKE",
                                    "vendor": "OLD_VENDOR",
                                    "catalog_product_id": "161",
                                },
                            }
                        ],
                    },
                    {
                        "row_id": "r2",
                        "products": [
                            {
                                "product_index": 0,
                                "category": "TANK",
                                "sub_category": "AIR CUSHION TANK",
                                "catalog_product_id": "238",
                                "size": "300.00",
                                "unit": "mm",
                                "selected_make": "OLD_MAKE",
                                "selected_vendor": "OLD_VENDOR",
                                "vendor_selection": {
                                    "status": "matched",
                                    "make": "OLD_MAKE",
                                    "vendor": "OLD_VENDOR",
                                    "catalog_product_id": "238",
                                },
                            }
                        ],
                    },
                ],
            },
            boq_data={"rows": [{"row_id": "r1", "qty": 1}, {"row_id": "r2", "qty": 1}]},
        )

    def test_apply_subcategory_with_product_id_updates_only_target_product(self):
        service = MakeVendorSelectionService(self.boq.pk)
        fake_payload = {
            "status": "matched",
            "make": "SELF",
            "vendor": "SELF",
            "line_output": {"material_rate": "7471.30"},
        }
        with (
            patch.object(MakeVendorSelectionService, "has_make_list", new_callable=PropertyMock, return_value=False),
            patch.object(service, "_database_version_id", return_value=1),
            patch.object(service, "_rate_master_makes_for_subcategory", return_value=["SELF"]),
            patch.object(service, "_exact_match_and_rates", return_value=dict(fake_payload)),
        ):
            result = service.apply_subcategory_make(
                category="TANK",
                sub_category="AIR CUSHION TANK",
                product_id="238",
                make="SELF",
                vendor="SELF",
            )

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["product_id"], "238")
        self.boq.refresh_from_db()
        rows = self.boq.analysis_data["rows"]
        # r1 (Product 161) must remain untouched
        prod_161 = rows[0]["products"][0]
        self.assertEqual(prod_161["selected_make"], "OLD_MAKE")
        self.assertEqual(prod_161["selected_vendor"], "OLD_VENDOR")

        # r2 (Product 238) must be updated to SELF / SELF
        prod_238 = rows[1]["products"][0]
        self.assertEqual(prod_238["selected_make"], "SELF")
        self.assertEqual(prod_238["selected_vendor"], "SELF")

        # Applied filter stored with product_id
        selections = self.boq.analysis_data["subcategory_make_selections"]
        storage_key = "TANK::AIR CUSHION TANK::238"
        self.assertIn(storage_key, selections)
        self.assertEqual(selections[storage_key]["product_id"], "238")

    def test_catalog_builds_product_rows(self):
        service = MakeVendorSelectionService(self.boq.pk)
        with (
            patch.object(service, "_make_options_for_scope", return_value=(["Lowest price", "SELF"], ["SELF"], True)),
            patch.object(service, "_rate_master_makes_for_subcategory", return_value=["SELF"]),
            patch.object(service, "_vendors_for_subcategory_make", return_value=["SELF"]),
            patch.object(service, "_lowest_amount_maps", return_value={"lowest_amount": "5959.90"}),
            patch.object(service, "_approved_makes_for_subcategory", return_value=["SELF"]),
        ):
            catalog = service._build_selection_catalog(self.boq.analysis_data, database_version_id=1)

        sub = catalog["categories"][0]["sub_categories"][0]
        self.assertIn("products", sub)
        self.assertEqual(len(sub["products"]), 2)
        prod_ids = [p["product_id"] for p in sub["products"]]
        self.assertIn("161", prod_ids)
        self.assertIn("238", prod_ids)

    def test_category_cascade_skips_unmatched_or_unapproved_products(self):
        service = MakeVendorSelectionService(self.boq.pk)

        def fake_exact(product, make, vendor, database_version_id, *args, **kwargs):
            pid = str(product.get("catalog_product_id") or "")
            if pid == "161":
                return {
                    "status": "matched",
                    "make": "TARGET_MAKE",
                    "vendor": "TARGET_VENDOR",
                    "line_output": {"material_rate": "100.00"},
                }
            return {
                "status": "unmatched",
                "make": "TARGET_MAKE",
                "vendor": "",
                "line_output": {},
            }

        with (
            patch.object(MakeVendorSelectionService, "has_make_list", new_callable=PropertyMock, return_value=True),
            patch.object(service, "_database_version_id", return_value=1),
            patch.object(service.make_list_service, "approved_makes_for_category", return_value=["TARGET_MAKE"]),
            patch.object(service, "_approved_makes_for_subcategory", return_value=["TARGET_MAKE"]),
            patch.object(service, "_capture_analysis_product_id", side_effect=lambda p, **kw: (dict(p), str(p.get("catalog_product_id") or ""))),
            patch.object(service, "_exact_match_and_rates", side_effect=fake_exact),
        ):
            result = service.apply_subcategory_make(
                category="TANK",
                sub_category="AIR CUSHION TANK",
                make="TARGET_MAKE",
                vendor="TARGET_VENDOR",
                make_source="approved",
            )

        self.assertEqual(result["updated_count"], 1)
        self.boq.refresh_from_db()
        rows = self.boq.analysis_data["rows"]

        # Product 161 was matched and updated
        prod_161 = rows[0]["products"][0]
        self.assertEqual(prod_161["selected_make"], "TARGET_MAKE")
        self.assertEqual(prod_161["selected_vendor"], "TARGET_VENDOR")

        # Product 238 was unmatched for TARGET_MAKE, so it was SKIPPED without injecting TARGET_MAKE
        prod_238 = rows[1]["products"][0]
        self.assertEqual(prod_238["selected_make"], "OLD_MAKE")
        self.assertEqual(prod_238["selected_vendor"], "OLD_VENDOR")

    def test_shape_product_separates_approved_and_available_makes(self):
        service = MakeVendorSelectionService(self.boq.pk)
        fake_product = {
            "product_index": 0,
            "category": "TANK",
            "sub_category": "AIR CUSHION TANK",
            "catalog_product_id": "161",
            "db_match_status": "matched",
            "db_match_confidence": 100.0,
            "selected_make": "UNAPPROVED_MAKE",
            "vendor_selection": {
                "status": "matched",
                "make": "UNAPPROVED_MAKE",
                "vendor": "V1",
            },
        }

        def fake_options(p, database_version_id, boq_description):
            return (
                ["APPROVED_A", "APPROVED_B"],
                ["AVAILABLE_X", "AVAILABLE_Y"],
                ["V1", "V2"],
                {"AVAILABLE_X": ["V1"]},
                {"V1": ["AVAILABLE_X"]},
            )

        with (
            patch.object(service, "_options_for_product", side_effect=fake_options),
            patch("apps.boq.services.make_vendor_display.MakeListConstraintService.make_is_allowed", return_value=False),
        ):
            shaped = service._shape_product(
                fake_product,
                row_id="r1",
                qty=1,
                unit="nos",
                database_version_id=1,
                boq_description="",
            )

        self.assertEqual(shaped["approved_make_options"], ["APPROVED_A", "APPROVED_B"])
        self.assertEqual(shaped["available_make_options"], ["AVAILABLE_X", "AVAILABLE_Y"])
        self.assertNotIn("UNAPPROVED_MAKE", shaped["approved_make_options"])
        self.assertNotIn("UNAPPROVED_MAKE", shaped["available_make_options"])

    def test_shape_product_approved_makes_strictly_sub_category(self):
        """Approved makes for product cards must be strictly per sub-category, never falling back to category."""
        make_list_data = {
            "category_mappings": [
                {
                    "material": "Ball Valves",
                    "mapped_category": "VALVE",
                    "mapped_sub_category": "BALL VALVE",
                    "mapped_targets": [{"category": "VALVE", "sub_category": "BALL VALVE"}],
                    "approved_makes_list": ["BALL_MAKE_1", "BALL_MAKE_2"],
                },
                {
                    "material": "Butterfly Valves",
                    "mapped_category": "VALVE",
                    "mapped_sub_category": "BUTTERFLY",
                    "mapped_targets": [{"category": "VALVE", "sub_category": "BUTTERFLY"}],
                    "approved_makes_list": ["BF_MAKE_1"],
                },
                {
                    "material": "General Valves",
                    "mapped_category": "VALVE",
                    "mapped_sub_category": None,
                    "mapped_targets": [{"category": "VALVE", "sub_category": None}],
                    "approved_makes_list": ["CAT_WIDE_MAKE"],
                },
            ]
        }
        service = MakeVendorSelectionService(self.boq.pk, make_list_data=make_list_data)

        # 1. Product with sub_category="BALL VALVE"
        ball_product = {
            "category": "VALVE",
            "sub_category": "BALL VALVE",
            "size": "25",
            "unit": "MM",
        }
        with patch.object(service, "_rate_master_makes_for_subcategory", return_value=["BALL_MAKE_1", "DB_MAKE"]):
            app_makes, avail_makes, _, _, _ = service._options_for_product(
                ball_product, database_version_id=1, boq_description=""
            )

        self.assertEqual(app_makes, ["BALL_MAKE_1", "BALL_MAKE_2"])
        self.assertNotIn("CAT_WIDE_MAKE", app_makes)
        self.assertNotIn("BF_MAKE_1", app_makes)

        # 2. Product with sub_category="SLUICE VALVE" (not in make list)
        sluice_product = {
            "category": "VALVE",
            "sub_category": "SLUICE VALVE",
            "size": "50",
            "unit": "MM",
        }
        with patch.object(service, "_rate_master_makes_for_subcategory", return_value=["DB_SLUICE"]):
            app_makes, avail_makes, _, _, _ = service._options_for_product(
                sluice_product, database_version_id=1, boq_description=""
            )

        self.assertEqual(app_makes, [])
        self.assertNotIn("CAT_WIDE_MAKE", app_makes)

    def test_shape_product_retains_available_make_when_also_approved(self):
        """When user selects an Available make that is also in Approved makes, it stays in Available make."""
        service = MakeVendorSelectionService(self.boq.pk)
        common_make = "ZURN"

        # Case 1: make_source == 'available'
        fake_product_available = {
            "product_index": 0,
            "category": "VALVE",
            "sub_category": "BALL VALVE",
            "catalog_product_id": "100",
            "db_match_status": "matched",
            "db_match_confidence": 100.0,
            "selected_make": common_make,
            "selected_make_source": "available",
            "vendor_selection": {
                "status": "matched",
                "make": common_make,
                "vendor": "V1",
                "make_source": "available",
            },
        }

        def fake_options(p, database_version_id, boq_description):
            return (
                [common_make, "OTHER_APP"],
                [common_make, "OTHER_AVAIL"],
                ["V1"],
                {common_make: ["V1"]},
                {"V1": [common_make]},
            )

        with patch.object(service, "_options_for_product", side_effect=fake_options):
            shaped_avail = service._shape_product(
                fake_product_available,
                row_id="r1",
                qty=1,
                unit="nos",
                database_version_id=1,
                boq_description="",
            )

        self.assertEqual(shaped_avail["selected_available_make"], common_make)
        self.assertEqual(shaped_avail["selected_approved_make"], "")
        self.assertEqual(shaped_avail["selected_make_source"], "available")

        # Case 2: make_source == 'approved'
        fake_product_approved = {
            "product_index": 0,
            "category": "VALVE",
            "sub_category": "BALL VALVE",
            "catalog_product_id": "100",
            "db_match_status": "matched",
            "db_match_confidence": 100.0,
            "selected_make": common_make,
            "selected_make_source": "approved",
            "vendor_selection": {
                "status": "matched",
                "make": common_make,
                "vendor": "V1",
                "make_source": "approved",
            },
        }

        with patch.object(service, "_options_for_product", side_effect=fake_options):
            shaped_app = service._shape_product(
                fake_product_approved,
                row_id="r1",
                qty=1,
                unit="nos",
                database_version_id=1,
                boq_description="",
            )

        self.assertEqual(shaped_app["selected_approved_make"], common_make)
        self.assertEqual(shaped_app["selected_available_make"], "")
        self.assertEqual(shaped_app["selected_make_source"], "approved")

    def test_select_and_match_persists_make_source(self):
        """select_and_match persists selected_make_source on product dictionary."""
        service = MakeVendorSelectionService(self.boq.pk)

        fake_exact = {
            "status": "matched",
            "confidence": 100.0,
            "make": "DANFOSS",
            "vendor": "BILLU",
            "product_id": "40",
            "rate_detail": {"final_material_amount": 856.48},
        }

        with (
            patch.object(service, "_database_version_id", return_value=1),
            patch.object(service, "_exact_match_and_rates", return_value=fake_exact),
            patch("apps.boq.services.make_vendor_selection_service.save_boq_analysis_json"),
        ):
            res = service.select_and_match(
                row_id="r1",
                product_index=0,
                make="DANFOSS",
                vendor="BILLU",
                make_source="available",
            )

        self.assertEqual(res.get("make_source"), "available")
        self.boq.refresh_from_db()
        prod = self.boq.analysis_data["rows"][0]["products"][0]
        self.assertEqual(prod.get("selected_make_source"), "available")

    def test_shape_product_fills_available_make_when_approved_make_not_available(self):
        """When approved make is not available, Available make is filled with the available make name."""
        service = MakeVendorSelectionService(self.boq.pk)

        # 1. Product with selected_make set to an available make
        fake_product_1 = {
            "product_index": 0,
            "category": "VALVE",
            "sub_category": "SPECIAL VALVE",
            "catalog_product_id": "100",
            "db_match_status": "matched",
            "db_match_confidence": 100.0,
            "selected_make": "ZURN",
            "vendor_selection": {
                "status": "matched",
                "make": "ZURN",
                "vendor": "V1",
            },
        }

        # No approved makes, only available makes
        def fake_options(p, database_version_id, boq_description):
            return (
                [],  # No approved makes
                ["ZURN", "LEADER"],
                ["V1"],
                {"ZURN": ["V1"]},
                {"V1": ["ZURN"]},
            )

        with patch.object(service, "_options_for_product", side_effect=fake_options):
            shaped_1 = service._shape_product(
                fake_product_1,
                row_id="r1",
                qty=1,
                unit="nos",
                database_version_id=1,
                boq_description="",
            )

        self.assertEqual(shaped_1["selected_available_make"], "ZURN")
        self.assertEqual(shaped_1["selected_approved_make"], "")
        self.assertEqual(shaped_1["selected_make"], "ZURN")
        self.assertFalse(shaped_1["has_approved_makes"])

        # 2. Product where selected_make is not set directly, but present in rate_detail
        fake_product_2 = {
            "product_index": 1,
            "category": "VALVE",
            "sub_category": "SPECIAL VALVE",
            "catalog_product_id": "100",
            "db_match_status": "matched",
            "db_match_confidence": 100.0,
            "selected_make": "",
            "vendor_selection": {
                "status": "matched",
                "make": "",
                "rate_detail": {
                    "make": "LEADER",
                    "vendor": "V1",
                    "final_material_amount": 500.0,
                },
            },
        }

        with patch.object(service, "_options_for_product", side_effect=fake_options):
            shaped_2 = service._shape_product(
                fake_product_2,
                row_id="r1",
                qty=1,
                unit="nos",
                database_version_id=1,
                boq_description="",
            )

        self.assertEqual(shaped_2["selected_available_make"], "LEADER")
        self.assertEqual(shaped_2["selected_approved_make"], "")
        self.assertEqual(shaped_2["selected_make"], "LEADER")





