"""Tests for the cost engine (Sprint 13 - material cost)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.costing.models import CostBreakdown
from apps.costing.services.cost_service import CostCalculationService
from apps.database_manager.models import (
    DatabaseVersion,
    LabourMaster,
    RateMaster,
    TORAccessories,
    TORLabour,
)
from apps.matching.models import ProductMatch


class MaterialCostTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="cost@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.rate = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="APL", vendor="V1", purchase_rate=Decimal("850.50"),
        )
        boq = BOQ.objects.create(user=self.user, boq_name="B", uploaded_file="boq/x.xlsx")
        self.run = BOQRun.objects.create(boq=boq, run_number=1)

    def _match(self, product, quantity="10"):
        item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal(quantity)
        )
        return ProductMatch.objects.create(
            boq_item=item, product=product, confidence_score=100, match_reason="exact"
        )

    def test_material_cost_uses_vendor_purchase_rate(self):
        match = self._match(self.rate)
        breakdown = CostCalculationService().calculate_item(match)
        self.assertEqual(breakdown.material_cost, Decimal("850.50"))

    def test_final_rate_equals_sum_of_components(self):
        match = self._match(self.rate)
        breakdown = CostCalculationService().calculate_item(match)
        expected = (
            breakdown.material_cost
            + breakdown.labour_cost
            + breakdown.accessories_cost
            + breakdown.transportation_cost
            + breakdown.overhead_cost
            + breakdown.profit
        )
        self.assertEqual(breakdown.final_rate, expected)

    def test_pending_item_gets_no_breakdown(self):
        match = self._match(product=None)
        result = CostCalculationService().calculate_item(match)
        self.assertIsNone(result)
        self.assertFalse(CostBreakdown.objects.filter(product_match=match).exists())

    def test_calculate_run_is_idempotent(self):
        self._match(self.rate)
        service = CostCalculationService()
        service.calculate_run(self.run)
        service.calculate_run(self.run)
        self.assertEqual(CostBreakdown.objects.count(), 1)

    def test_recompute_sums_all_components(self):
        from apps.costing.services.cost_service import recompute_final_rate

        match = self._match(self.rate)
        breakdown = CostCalculationService().calculate_item(match)
        breakdown.material_cost = Decimal("500.00")
        breakdown.labour_cost = Decimal("100.00")
        breakdown.accessories_cost = Decimal("50.00")
        breakdown.transportation_cost = Decimal("10.00")
        breakdown.overhead_cost = Decimal("66.00")
        breakdown.profit = Decimal("72.60")
        recompute_final_rate(breakdown)
        self.assertEqual(breakdown.final_rate, Decimal("798.60"))


class LabourCostTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="lab@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.pipe = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="APL", vendor="V1", purchase_rate=Decimal("850.50"),
        )
        # Accessory product (priced via RateMaster).
        RateMaster.objects.create(
            database_version=self.version, product_code="CLAMP1",
            description="Pipe clamp", purchase_rate=Decimal("20.00"),
        )
        LabourMaster.objects.create(
            database_version=self.version, labour_code="L1", labour_name="Fitter",
            labour_rate=Decimal("50.00"),
        )
        TORLabour.objects.create(
            database_version=self.version, tor_code="PIPE150", labour_code="L1",
            quantity=Decimal("2"),
        )
        TORAccessories.objects.create(
            database_version=self.version, tor_code="PIPE150", accessory_code="CLAMP1",
            quantity=Decimal("3"),
        )
        boq = BOQ.objects.create(user=self.user, boq_name="B", uploaded_file="boq/x.xlsx")
        self.run = BOQRun.objects.create(boq=boq, run_number=1)
        item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal("10")
        )
        self.match = ProductMatch.objects.create(
            boq_item=item, product=self.pipe, confidence_score=100, match_reason="exact"
        )

    def test_labour_cost_expands_from_tor(self):
        breakdown = CostCalculationService().calculate_item(self.match)
        self.assertEqual(breakdown.labour_cost, Decimal("100.00"))  # 2 x 50

    def test_accessories_cost_expands_from_tor(self):
        breakdown = CostCalculationService().calculate_item(self.match)
        self.assertEqual(breakdown.accessories_cost, Decimal("60.00"))  # 3 x 20

    def test_final_rate_sums_all_components(self):
        breakdown = CostCalculationService().calculate_item(self.match)
        expected = (
            breakdown.material_cost
            + breakdown.labour_cost
            + breakdown.accessories_cost
            + breakdown.transportation_cost
            + breakdown.overhead_cost
            + breakdown.profit
        )
        self.assertEqual(breakdown.final_rate, expected)

    def test_missing_labour_rate_is_skipped(self):
        TORLabour.objects.create(
            database_version=self.version, tor_code="PIPE150", labour_code="UNKNOWN",
            quantity=Decimal("5"),
        )
        breakdown = CostCalculationService().calculate_item(self.match)
        self.assertEqual(breakdown.labour_cost, Decimal("100.00"))  # unknown skipped


class CommercialCostingTests(TestCase):
    def setUp(self):
        from apps.database_manager.models import StateControl

        self.user = get_user_model().objects.create_user(email="com@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.rate = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="APL", vendor="V1", purchase_rate=Decimal("850.50"),
        )
        LabourMaster.objects.create(
            database_version=self.version, labour_code="L1", labour_name="Fitter",
            labour_rate=Decimal("50.00"),
        )
        TORLabour.objects.create(
            database_version=self.version, tor_code="PIPE150", labour_code="L1",
            quantity=Decimal("2"),
        )
        StateControl.objects.create(
            state_name="Maharashtra", labour_multiplier=Decimal("2"),
            transportation_multiplier=Decimal("3"),
        )
        boq = BOQ.objects.create(user=self.user, boq_name="B", uploaded_file="boq/x.xlsx")
        self.run = BOQRun.objects.create(boq=boq, run_number=1)
        item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal("1")
        )
        self.match = ProductMatch.objects.create(
            boq_item=item, product=self.rate, confidence_score=100, match_reason="exact"
        )

    def test_commercial_components_with_defaults(self):
        # material=850.50, labour=100, transport=2% material=17.01
        # base=967.51, overhead=10%=96.75, profit=10% of 1064.26=106.43
        breakdown = CostCalculationService().calculate_item(self.match)
        self.assertEqual(breakdown.transportation_cost, Decimal("17.01"))
        self.assertEqual(breakdown.overhead_cost, Decimal("96.75"))
        self.assertEqual(breakdown.profit, Decimal("106.43"))
        self.assertEqual(breakdown.final_rate, Decimal("1170.69"))

    def test_state_multipliers_applied(self):
        CostCalculationService().calculate_run(self.run, state_name="Maharashtra")
        breakdown = self.match.cost_breakdown
        self.assertEqual(breakdown.labour_cost, Decimal("200.00"))  # 100 x 2
        self.assertEqual(breakdown.transportation_cost, Decimal("51.03"))  # 17.01 x 3

    def test_unknown_state_uses_neutral_multipliers(self):
        CostCalculationService().calculate_run(self.run, state_name="Atlantis")
        breakdown = self.match.cost_breakdown
        self.assertEqual(breakdown.labour_cost, Decimal("100.00"))
