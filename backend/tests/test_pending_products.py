"""Tests for the pending product workflow (Sprint 18)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.database_manager.models import DatabaseVersion, ProductAlias, RateMaster
from apps.pending_products.models import PendingProduct
from apps.pending_products.services.pending_service import PendingProductService
from common.choices import PendingProductStatus, UserRole
from common.exceptions import ValidationError


class PendingServiceTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(email="a@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.rate = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", purchase_rate=Decimal("800.00"),
        )
        self.pending = PendingProduct.objects.create(
            description="150NB pipe unknown", confidence_score=Decimal("12.00")
        )

    def test_reject(self):
        PendingProductService().reject(self.pending, self.admin)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingProductStatus.REJECTED)
        self.assertEqual(self.pending.reviewed_by, self.admin)

    def test_merge_creates_alias_and_approves(self):
        PendingProductService().merge(self.pending, "PIPE150", user=self.admin)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingProductStatus.APPROVED)
        self.assertTrue(
            ProductAlias.objects.filter(
                alias="150NB pipe unknown", product_code="PIPE150"
            ).exists()
        )

    def test_merge_unknown_code_raises(self):
        with self.assertRaises(ValidationError):
            PendingProductService().merge(self.pending, "NOPE", user=self.admin)

    def test_add_new_creates_rate_and_alias(self):
        PendingProductService().add_new(
            self.pending, product_code="VALVE9", description="Gate valve",
            purchase_rate=Decimal("499.99"), make="Zoloto", user=self.admin,
        )
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingProductStatus.APPROVED)
        rate = RateMaster.objects.get(database_version=self.version, product_code="VALVE9")
        self.assertEqual(rate.purchase_rate, Decimal("499.99"))
        self.assertTrue(ProductAlias.objects.filter(product_code="VALVE9").exists())

    def test_add_new_duplicate_code_raises(self):
        with self.assertRaises(ValidationError):
            PendingProductService().add_new(
                self.pending, product_code="PIPE150", user=self.admin
            )


class PendingViewAccessTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(email="adm@x.com", password="x")
        self.expert = get_user_model().objects.create_user(
            email="exp@x.com", password="x", role=UserRole.EXPERT
        )
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", purchase_rate=Decimal("800.00"),
        )
        self.pending = PendingProduct.objects.create(
            description="unknown thing", confidence_score=Decimal("10.00")
        )

    def test_admin_sees_list(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("pending_products:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "unknown thing")

    def test_expert_forbidden(self):
        self.client.force_login(self.expert)
        resp = self.client.get(reverse("pending_products:list"))
        self.assertEqual(resp.status_code, 403)

    def test_admin_merge_via_view(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("pending_products:merge", args=[self.pending.pk]),
            {"product_code": "PIPE150"},
        )
        self.assertEqual(resp.status_code, 302)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingProductStatus.APPROVED)

    def test_expert_cannot_reject(self):
        self.client.force_login(self.expert)
        resp = self.client.post(reverse("pending_products:reject", args=[self.pending.pk]))
        self.assertEqual(resp.status_code, 403)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PendingProductStatus.PENDING)
