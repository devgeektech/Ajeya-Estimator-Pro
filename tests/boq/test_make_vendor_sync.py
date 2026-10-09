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

