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
from common.choices import BOQStatus, RunStatus
from common.exceptions import ValidationError


class ReviewServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="r@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.cheap = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="APL", vendor="V1", purchase_rate=Decimal("800.00"),
        )
        self.pricey = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="Tata", vendor="V2", purchase_rate=Decimal("1000.00"),
        )
        self.other = RateMaster.objects.create(
            database_version=self.version, product_code="VALVE1",
            description="Gate valve", make="Zoloto", vendor="V3", purchase_rate=Decimal("500.00"),
        )
        self.boq = BOQ.objects.create(
            user=self.user, boq_name="B", uploaded_file="boq/x.xlsx", status=BOQStatus.COMPLETED
        )
        self.run = BOQRun.objects.create(boq=self.boq, run_number=1, status=RunStatus.COMPLETED)
        self.item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal("1")
        )
        self.match = ProductMatch.objects.create(
            boq_item=self.item, product=self.cheap, make="APL", vendor="V1",
            confidence_score=90, match_reason="exact",
        )

    def test_candidate_rates_same_product_code(self):
        candidates = list(ReviewService().candidate_rates(self.item))
        self.assertIn(self.cheap, candidates)
        self.assertIn(self.pricey, candidates)
        self.assertNotIn(self.other, candidates)

    def test_apply_selection_changes_vendor_and_recalcs(self):
        ReviewService().apply_selection(self.item, self.pricey, user=self.user)
        self.match.refresh_from_db()
        self.assertEqual(self.match.product, self.pricey)
        self.assertEqual(self.match.vendor, "V2")
        self.assertEqual(float(self.match.confidence_score), 100.0)
        # Cost recalculated from the new (pricier) vendor rate.
        self.assertEqual(self.match.cost_breakdown.material_cost, Decimal("1000.00"))

    def test_apply_selection_records_review_item(self):
        ReviewService().apply_selection(self.item, self.pricey, user=self.user)
        review = ReviewItem.objects.get(boq_item=self.item)
        self.assertEqual(review.original_vendor, "V1")
        self.assertEqual(review.revised_vendor, "V2")
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
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="APL", vendor="V1", purchase_rate=Decimal("800.00"),
        )
        self.alt = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="Tata", vendor="V2", purchase_rate=Decimal("1000.00"),
        )
        self.boq = BOQ.objects.create(
            user=self.owner, boq_name="B", uploaded_file="boq/x.xlsx", status=BOQStatus.COMPLETED
        )
        self.run = BOQRun.objects.create(boq=self.boq, run_number=1, status=RunStatus.COMPLETED)
        self.item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", quantity=Decimal("1")
        )
        self.match = ProductMatch.objects.create(
            boq_item=self.item, product=self.rate, make="APL", vendor="V1",
            confidence_score=90, match_reason="exact",
        )

    def test_owner_can_view_review(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("review:detail", args=[self.boq.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "150 NB MS Pipe")

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
        self.assertEqual(self.match.vendor, "V2")

    def test_non_owner_apply_forbidden(self):
        self.client.force_login(self.other)
        resp = self.client.post(
            reverse("review:apply", args=[self.item.pk]), {"rate_id": self.alt.pk}
        )
        self.assertEqual(resp.status_code, 403)
        self.match.refresh_from_db()
        self.assertEqual(self.match.vendor, "V1")  # unchanged

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
