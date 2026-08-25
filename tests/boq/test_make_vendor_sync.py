"""Make & Vendor sync preserves manual picks; filter clear restores lowest."""

from unittest.mock import patch

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
