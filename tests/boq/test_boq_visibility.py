"""BOQ visibility by role."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.boq.models import BOQ
from apps.boq.services.boq_visibility_service import boqs_visible_to_user
from common.choices import BOQStatus, UserRole

User = get_user_model()


class BOQVisibilityServiceTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            email="super@example.com", password="password"
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )
        self.admin2 = User.objects.create_user(
            email="admin2@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )
        # Underling of admin
        self.expert = User.objects.create_user(
            email="expert@example.com",
            password="password",
            role=UserRole.EXPERT,
            created_by=self.admin,
        )
        # Underling of admin2 — must not appear for admin
        self.expert2 = User.objects.create_user(
            email="expert2@example.com",
            password="password",
            role=UserRole.EXPERT,
            created_by=self.admin2,
        )

        self.boq_super = BOQ.objects.create(
            boq_name="Super BOQ",
            status=BOQStatus.UPLOADED,
            user=self.superadmin,
            uploaded_file="boq/super.xlsx",
        )
        self.boq_admin = BOQ.objects.create(
            boq_name="Admin BOQ",
            status=BOQStatus.UPLOADED,
            user=self.admin,
            uploaded_file="boq/admin.xlsx",
        )
        self.boq_admin2 = BOQ.objects.create(
            boq_name="Admin2 BOQ",
            status=BOQStatus.UPLOADED,
            user=self.admin2,
            uploaded_file="boq/admin2.xlsx",
        )
        self.boq_expert = BOQ.objects.create(
            boq_name="Expert BOQ",
            status=BOQStatus.UPLOADED,
            user=self.expert,
            uploaded_file="boq/expert.xlsx",
        )
        self.boq_expert2 = BOQ.objects.create(
            boq_name="Expert2 BOQ",
            status=BOQStatus.UPLOADED,
            user=self.expert2,
            uploaded_file="boq/expert2.xlsx",
        )

    def test_expert_sees_only_own(self):
        ids = set(boqs_visible_to_user(self.expert).values_list("pk", flat=True))
        self.assertEqual(ids, {self.boq_expert.pk})

    def test_superadmin_sees_all_boqs(self):
        ids = set(boqs_visible_to_user(self.superadmin).values_list("pk", flat=True))
        self.assertEqual(
            ids,
            {
                self.boq_super.pk,
                self.boq_admin.pk,
                self.boq_admin2.pk,
                self.boq_expert.pk,
                self.boq_expert2.pk,
            },
        )

    def test_admin_sees_own_and_own_experts_only(self):
        ids = set(boqs_visible_to_user(self.admin).values_list("pk", flat=True))
        self.assertEqual(ids, {self.boq_admin.pk, self.boq_expert.pk})
        self.assertNotIn(self.boq_admin2.pk, ids)
        self.assertNotIn(self.boq_expert2.pk, ids)
        self.assertNotIn(self.boq_super.pk, ids)

    def test_admin2_sees_own_and_own_experts_only(self):
        ids = set(boqs_visible_to_user(self.admin2).values_list("pk", flat=True))
        self.assertEqual(ids, {self.boq_admin2.pk, self.boq_expert2.pk})
        self.assertNotIn(self.boq_admin.pk, ids)
        self.assertNotIn(self.boq_expert.pk, ids)

    def test_admin_can_open_own_expert_boq_detail(self):
        self.client.login(email="admin@example.com", password="password")
        url = reverse("boq:detail", args=[self.boq_expert.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_admin_cannot_open_other_admins_expert_boq(self):
        self.client.login(email="admin@example.com", password="password")
        url = reverse("boq:detail", args=[self.boq_expert2.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_expert_cannot_open_other_expert_boq(self):
        self.client.login(email="expert@example.com", password="password")
        url = reverse("boq:detail", args=[self.boq_expert2.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_superadmin_can_open_expert_boq(self):
        self.client.login(email="super@example.com", password="password")
        url = reverse("boq:detail", args=[self.boq_expert.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
