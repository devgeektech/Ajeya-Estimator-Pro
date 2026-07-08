"""Tests for rate and labour detail retrieval."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.costing.models import RateDetail
from apps.costing.services.rate_detail import RateDetailRetrievalService
from apps.database_manager.models import DatabaseVersion, LabourMaster, LabourStructureSource, RateMaster
from apps.matching.models import ProductMatch


class RateDetailRetrievalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="rate@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.rate = RateMaster.objects.create(
            database_version=self.version,
            tech_key="PIPE150",
            category="Pipes",
            sub_category="MS",
            size_mm=Decimal("150"),
            unit="m",
            make="APL",
            supplier="S1",
            base_purchase_rate=Decimal("1000.00"),
            discount_percent=Decimal("10.00"),
            net_material_rate=Decimal("900.00"),
            commercial_material_base=Decimal("900.00"),
            accessories_value=Decimal("90.00"),
            handling_value=Decimal("10.00"),
            wastage_value=Decimal("5.00"),
            subtotal_before_profit=Decimal("1005.00"),
            profit_value=Decimal("100.50"),
            final_expenditure=Decimal("1105.50"),
            final_amount_excl_gst=Decimal("1200.00"),
            margin_percent_on_selling=Decimal("8.00"),
        )
        self.labour = LabourMaster.objects.create(
            database_version=self.version,
            tech_key="PIPE150",
            state="Maharashtra",
            labour_type="Fitter",
            labour_rate_per_unit=Decimal("25.00"),
            total_labour_per_unit=Decimal("100.00"),
            total_labour_with_multiplier=Decimal("125.00"),
        )
        boq = BOQ.objects.create(user=self.user, boq_name="B", uploaded_file="boq/x.xlsx")
        self.run = BOQRun.objects.create(boq=boq, run_number=1)

    def _match(self, *, quantity="10", product_quantity="1", basis="per_boq_unit"):
        item = BOQItem.objects.create(
            boq_run=self.run,
            row_number=1,
            target_excel_row=1,
            description="150 NB MS Pipe",
            quantity=Decimal(quantity),
            unit="m",
        )
        return ProductMatch.objects.create(
            boq_item=item,
            product=self.rate,
            confidence_score=100,
            match_reason="exact",
            match_type="exact",
            product_quantity=Decimal(product_quantity),
            product_unit="m",
            quantity_basis=basis,
        )

    def test_retrieves_rate_master_and_labour_master_fields(self):
        match = self._match()
        detail = RateDetailRetrievalService().retrieve_item(match)

        self.assertEqual(detail.tech_key, "PIPE150")
        self.assertEqual(detail.final_amount_excl_gst, Decimal("1200.00"))
        self.assertEqual(detail.net_material_rate, Decimal("900.00"))
        self.assertEqual(detail.labour_master_id, self.labour.pk)
        self.assertEqual(detail.total_labour_with_multiplier, Decimal("125.00"))

    def test_pending_item_gets_no_rate_detail(self):
        match = self._match()
        match.product = None
        match.save(update_fields=["product"])

        result = RateDetailRetrievalService().retrieve_item(match)

        self.assertIsNone(result)
        self.assertFalse(RateDetail.objects.filter(product_match=match).exists())

    def test_retrieve_run_is_idempotent(self):
        self._match()
        service = RateDetailRetrievalService()

        service.retrieve_run(self.run)
        service.retrieve_run(self.run)

        self.assertEqual(RateDetail.objects.count(), 1)

    def test_per_boq_unit_quantity_sets_rate_contribution(self):
        match = self._match(product_quantity="2", basis="per_boq_unit")

        detail = RateDetailRetrievalService().retrieve_item(match)

        self.assertEqual(detail.rate_contribution, Decimal("2400.00"))

    def test_total_for_boq_row_quantity_sets_rate_contribution(self):
        match = self._match(quantity="4", product_quantity="8", basis="total_for_boq_row")

        detail = RateDetailRetrievalService().retrieve_item(match)

        self.assertEqual(detail.rate_contribution, Decimal("2400.00"))

    def test_unknown_quantity_basis_blanks_contribution(self):
        match = self._match(product_quantity="2", basis="unknown")

        detail = RateDetailRetrievalService().retrieve_item(match)

        self.assertEqual(detail.rate_contribution, Decimal("0.00"))

    def test_labour_structure_source_fallback(self):
        LabourMaster.objects.filter(database_version=self.version).delete()
        fallback = LabourMaster.objects.create(
            database_version=self.version,
            tech_key="L1",
            labour_type="Fitter",
            total_labour_with_multiplier=Decimal("75.00"),
        )
        LabourStructureSource.objects.create(
            database_version=self.version,
            category="Pipes",
            sub_category="MS",
            size="150",
            unit="m",
            tech_key="L1",
        )
        match = self._match()

        detail = RateDetailRetrievalService().retrieve_item(match)

        self.assertEqual(detail.labour_master_id, fallback.pk)
        self.assertEqual(detail.total_labour_with_multiplier, Decimal("75.00"))
