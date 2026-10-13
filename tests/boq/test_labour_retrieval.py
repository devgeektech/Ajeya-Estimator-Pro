"""Unit tests for LabourDetailRetrievalService and database version resolution fallbacks."""
from decimal import Decimal
from django.test import TestCase

from apps.boq.models import BOQ
from apps.boq.services.boq_labour_service import BOQLabourService
from apps.boq.services.labour_detail_retrieval_service import LabourDetailRetrievalService
from apps.boq.services.rate_detail_retrieval_service import RateDetailRetrievalService
from apps.database_manager.models import DatabaseVersion, Labour_master_Output, Rate_Master_Output
from apps.database_manager.services.activation import (
    activate_database_version,
    resolve_active_database_version_id,
)
from apps.accounts.models import User


class LabourRetrievalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="labour_test@example.com", password="password123")
        self.v1 = DatabaseVersion.objects.create(
            version_number=1,
            name="Version 1",
            is_active=False,
            uploaded_by=self.user,
        )
        self.v2 = DatabaseVersion.objects.create(
            version_number=2,
            name="Version 2",
            is_active=True,
            uploaded_by=self.user,
        )
        # Create Labour row in active version 2
        self.labour_row = Labour_master_Output.objects.create(
            database_version=self.v2,
            Product_ID="154",
            Category="HYDRANT",
            Sub_Category="FIRE HOSE BOX",
            Labour_Rate_Per_unit=Decimal("500.00"),
            Total_Labour_per_Unit=Decimal("505.00"),
            Total_Labour_per_unit_with_labour_Multipler=Decimal("505.00"),
        )
        # Create Rate row in active version 2
        self.rate_row = Rate_Master_Output.objects.create(
            database_version=self.v2,
            Product_ID="154",
            Rate_ID="217",
            Category="HYDRANT",
            Sub_Category="FIRE HOSE BOX",
            Make="SAFEGUARD",
            Vendor="OEM",
            Final_Material_Amount=Decimal("4645.08"),
        )

    def test_resolve_active_database_version_id(self):
        # Preferred is active v2
        self.assertEqual(resolve_active_database_version_id(self.v2.pk), self.v2.pk)
        # Preferred is inactive v1 -> falls back to v2
        self.assertEqual(resolve_active_database_version_id(self.v1.pk), self.v2.pk)
        # Preferred is None -> falls back to v2
        self.assertEqual(resolve_active_database_version_id(None), self.v2.pk)
        # Preferred is non-existent 9999 -> falls back to v2
        self.assertEqual(resolve_active_database_version_id(9999), self.v2.pk)

    def test_labour_detail_retrieval_service_fallback(self):
        # When initialized with stale inactive v1 ID, should fall back to active v2
        service = LabourDetailRetrievalService(self.v1.pk)
        self.assertEqual(service.database_version_id, self.v2.pk)
        res = service.get_by_product_id("154")
        self.assertIsNotNone(res)
        self.assertEqual(res["product_id"], "154")
        self.assertEqual(res["effective_labour_rate"], "505.00")

    def test_labour_detail_retrieval_service_float_id_fallback(self):
        # "154.0" should match "154"
        service = LabourDetailRetrievalService(self.v2.pk)
        res = service.get_by_product_id("154.0")
        self.assertIsNotNone(res)
        self.assertEqual(res["product_id"], "154")

    def test_rate_detail_retrieval_service_fallback(self):
        # When initialized with stale inactive v1 ID, should fall back to active v2
        service = RateDetailRetrievalService(self.v1.pk)
        self.assertEqual(service.database_version_id, self.v2.pk)
        res = service.get_by_id(self.rate_row.pk)
        self.assertIsNotNone(res)
        self.assertEqual(res["product_id"], "154")

    def test_boq_labour_service_database_version_resolution(self):
        boq = BOQ.objects.create(
            user=self.user,
            boq_name="Stale DB BOQ",
            analysis_data={"database_version_id": self.v1.pk, "rows": []},
        )
        service = BOQLabourService(boq.pk)
        resolved_id = service._database_version_id(boq)
        self.assertEqual(resolved_id, self.v2.pk)
        self.assertEqual(boq.analysis_data["database_version_id"], self.v2.pk)
