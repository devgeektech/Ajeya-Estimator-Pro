"""Tests for the review workflow (Sprint 16)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.database_manager.models import DatabaseVersion, RateMaster
from apps.matching.models import ProductMatch
from apps.review.models import ReviewItem
from apps.review.services.review_service import ReviewService
from apps.review.services.row_context import build_review_row_context
from common.choices import BOQStatus, RunStatus
from common.exceptions import ValidationError


class ReviewServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="r@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.cheap = RateMaster.objects.create(
            database_version=self.version,
            tech_key="PIPE150",
            make="APL",
            supplier="V1",
            net_material_rate=Decimal("800.00"),
            final_amount_excl_gst=Decimal("800.00"),
        )
        self.pricey = RateMaster.objects.create(
            database_version=self.version,
            tech_key="PIPE150",
            make="Tata",
            supplier="V2",
            net_material_rate=Decimal("1000.00"),
            final_amount_excl_gst=Decimal("1000.00"),
        )
        self.other = RateMaster.objects.create(
            database_version=self.version,
            tech_key="VALVE1",
            make="Zoloto",
            supplier="V3",
            net_material_rate=Decimal("500.00"),
            final_amount_excl_gst=Decimal("500.00"),
        )
        self.boq = BOQ.objects.create(
            user=self.user, boq_name="B", uploaded_file="boq/x.xlsx", status=BOQStatus.COMPLETED
        )
        self.run = BOQRun.objects.create(boq=self.boq, run_number=1, status=RunStatus.COMPLETED)
        self.item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal("1")
        )
        self.match = ProductMatch.objects.create(
            boq_item=self.item, product=self.cheap, make="APL", supplier="V1",
            confidence_score=90, match_reason="exact",
        )

    def test_candidate_rates_same_tech_key(self):
        candidates = list(ReviewService().candidate_rates(self.item))
        self.assertIn(self.cheap, candidates)
        self.assertIn(self.pricey, candidates)
        self.assertNotIn(self.other, candidates)

    def test_apply_selection_changes_supplier_and_recalcs(self):
        ReviewService().apply_selection(self.item, self.pricey, user=self.user)
        self.match.refresh_from_db()
        self.assertEqual(self.match.product, self.pricey)
        self.assertEqual(self.match.supplier, "V2")
        self.assertEqual(float(self.match.confidence_score), 100.0)
        self.assertEqual(self.match.rate_detail.net_material_rate, Decimal("1000.00"))

    def test_apply_selection_records_review_item(self):
        ReviewService().apply_selection(self.item, self.pricey, user=self.user)
        review = ReviewItem.objects.get(boq_item=self.item)
        self.assertEqual(review.original_supplier, "V1")
        self.assertEqual(review.revised_supplier, "V2")
        self.assertEqual(review.reviewed_by, self.user)

    def test_apply_selection_moves_boq_under_review(self):
        ReviewService().apply_selection(self.item, self.pricey, user=self.user)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.UNDER_REVIEW)

    def test_start_review_transitions_status(self):
        ReviewService().start_review(self.boq, self.user)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.UNDER_REVIEW)

    def test_approve_from_completed(self):
        ReviewService().approve(self.boq, self.user)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.APPROVED)

    def test_approve_from_under_review(self):
        self.boq.status = BOQStatus.UNDER_REVIEW
        self.boq.save(update_fields=["status"])
        ReviewService().approve(self.boq, self.user)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.APPROVED)

    def test_approve_invalid_state_raises(self):
        self.boq.status = BOQStatus.UPLOADED
        self.boq.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            ReviewService().approve(self.boq, self.user)

    def test_revise_reopens_approved(self):
        self.boq.status = BOQStatus.APPROVED
        self.boq.save(update_fields=["status"])
        ReviewService().revise(self.boq, self.user)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.UNDER_REVIEW)

    def test_revise_requires_approved(self):
        with self.assertRaises(ValidationError):
            ReviewService().revise(self.boq, self.user)  # still COMPLETED


class ReviewViewTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(email="own@x.com", password="x")
        self.other = get_user_model().objects.create_user(email="oth@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.rate = RateMaster.objects.create(
            database_version=self.version,
            tech_key="PIPE150",
            make="APL",
            supplier="V1",
            net_material_rate=Decimal("800.00"),
        )
        self.alt = RateMaster.objects.create(
            database_version=self.version,
            tech_key="PIPE150",
            make="Tata",
            supplier="V2",
            net_material_rate=Decimal("1000.00"),
        )
        self.boq = BOQ.objects.create(
            user=self.owner, boq_name="B", uploaded_file="boq/x.xlsx", status=BOQStatus.COMPLETED
        )
        self.run = BOQRun.objects.create(boq=self.boq, run_number=1, status=RunStatus.COMPLETED)
        self.item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal("1")
        )
        self.match = ProductMatch.objects.create(
            boq_item=self.item, product=self.rate, make="APL", supplier="V1",
            confidence_score=90, match_reason="exact",
        )
        self.item.ai_extraction = {
            "database_products": [
                {
                    "product_name": "MS Pipe",
                    "matched_product": {"tech_key": "PIPE150"},
                    "confidence_score": 90,
                }
            ],
            "missing_products": [{"product_name": "Gasket set"}],
            "database_activities": ["installation"],
            "missing_activities": ["scaffolding"],
            "activities": ["installation"],
        }
        self.item.save(update_fields=["ai_extraction"])

    def test_owner_can_view_review(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("review:detail", args=[self.boq.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "150 NB MS Pipe")
        self.assertContains(resp, "Products in database")
        self.assertContains(resp, "Products not in database")
        self.assertContains(resp, "Activities in database")
        self.assertContains(resp, "Activities not in database")
        self.assertContains(resp, "Gasket set")
        self.assertContains(resp, "scaffolding")
        self.assertContains(resp, "Generate preview workbook")

    def test_row_context_splits_products_and_activities(self):
        row = build_review_row_context(self.item, ReviewService())
        self.assertEqual(len(row["database_products"]), 1)
        self.assertEqual(len(row["missing_products"]), 1)
        self.assertEqual(row["database_activities"], ["installation"])
        self.assertEqual(row["missing_activities"], ["scaffolding"])

    def test_non_owner_cannot_view(self):
        self.client.force_login(self.other)
        resp = self.client.get(reverse("review:detail", args=[self.boq.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_apply_updates_row_via_htmx(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("review:apply", args=[self.item.pk]),
            {"rate_id": self.alt.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.match.refresh_from_db()
        self.assertEqual(self.match.supplier, "V2")

    def test_non_owner_apply_forbidden(self):
        self.client.force_login(self.other)
        resp = self.client.post(
            reverse("review:apply", args=[self.item.pk]), {"rate_id": self.alt.pk}
        )
        self.assertEqual(resp.status_code, 403)
        self.match.refresh_from_db()
        self.assertEqual(self.match.supplier, "V1")  # unchanged

    def test_owner_can_approve(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("review:approve", args=[self.boq.pk]))
        self.assertEqual(resp.status_code, 302)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.APPROVED)

    def test_non_owner_cannot_approve(self):
        self.client.force_login(self.other)
        resp = self.client.post(reverse("review:approve", args=[self.boq.pk]))
        self.assertEqual(resp.status_code, 404)
        self.boq.refresh_from_db()
        self.assertEqual(self.boq.status, BOQStatus.COMPLETED)
