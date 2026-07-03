"""Tests for the product matching engine (Sprint 10).

Exact/alias matching needs no AI. Vector matching mocks the embedding call so no
real API requests are made.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.boq.models import BOQ, BOQItem, BOQRun
from apps.database_manager.models import (
    DatabaseVersion,
    ProductAlias,
    ProductEmbedding,
    RateMaster,
)
from apps.matching.models import ProductMatch
from apps.matching.services.confidence import ConfidenceService, band_for
from apps.matching.services.matching_service import ProductMatchingService
from apps.matching.services.vendor_selection import VendorSelectionService
from apps.make_list.models import MakeListEntry
from apps.pending_products.models import PendingProduct
from common.choices import VendorSelectionMode


class MatchingEngineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="e@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.pipe = RateMaster.objects.create(
            database_version=self.version,
            product_code="PIPE150",
            description="150 NB MS Pipe",
            make="Jindal",
            vendor="ACME",
            purchase_rate=1000,
        )
        boq = BOQ.objects.create(user=self.user, boq_name="B", uploaded_file="boq/x.xlsx")
        self.run = BOQRun.objects.create(boq=boq, run_number=1)

    def _item(self, description, extraction=None):
        return BOQItem.objects.create(
            boq_run=self.run, row_number=1, description=description, ai_extraction=extraction
        )

    def test_exact_match_by_description(self):
        item = self._item("150 NB MS Pipe")
        ProductMatchingService().match_item(item)
        match = ProductMatch.objects.get(boq_item=item)
        self.assertEqual(match.product, self.pipe)
        self.assertEqual(match.match_reason, "exact")
        self.assertEqual(float(match.confidence_score), 100.0)
        self.assertEqual(match.vendor, "ACME")

    def test_exact_match_by_product_code(self):
        item = self._item("pipe150")
        ProductMatchingService().match_item(item)
        match = ProductMatch.objects.get(boq_item=item)
        self.assertEqual(match.product, self.pipe)
        self.assertEqual(match.match_reason, "exact")

    def test_alias_match(self):
        ProductAlias.objects.create(alias="ERW Pipe 150", product_code="PIPE150")
        item = self._item("Supply of ERW Pipe 150 for water line")
        ProductMatchingService().match_item(item)
        match = ProductMatch.objects.get(boq_item=item)
        self.assertEqual(match.product, self.pipe)
        self.assertEqual(match.match_reason, "alias")
        self.assertEqual(float(match.confidence_score), 90.0)

    def test_no_match_creates_pending_product(self):
        item = self._item("Unknown exotic widget")
        ProductMatchingService().match_item(item, created_by=self.user)
        match = ProductMatch.objects.get(boq_item=item)
        self.assertIsNone(match.product)
        self.assertEqual(match.match_reason, "no_match")
        self.assertEqual(float(match.confidence_score), 0.0)
        pending = PendingProduct.objects.get(boq_item=item)
        self.assertEqual(pending.created_by, self.user)

    @override_settings(OPENAI_API_KEY="sk-realLookingKey123")
    @mock.patch("ai.embeddings.generator.generate_embedding")
    def test_vector_match_when_ai_enabled(self, generate_embedding):
        ProductEmbedding.objects.create(product_code="PIPE150", embedding_vector=[1.0, 0.0, 0.0])
        generate_embedding.return_value = [0.9, 0.1, 0.0]
        item = self._item("MS tubular conduit", {"product": "tubular conduit"})

        ProductMatchingService().match_item(item)

        match = ProductMatch.objects.get(boq_item=item)
        self.assertEqual(match.product, self.pipe)
        self.assertEqual(match.match_reason, "vector")
        self.assertGreater(float(match.confidence_score), 30.0)

    def test_match_run_is_idempotent(self):
        self._item("150 NB MS Pipe")
        service = ProductMatchingService()
        service.match_run(self.run)
        service.match_run(self.run)
        self.assertEqual(ProductMatch.objects.count(), 1)

    def test_low_confidence_vector_routes_to_pending(self):
        # AI disabled -> vector skipped -> no match -> pending; product blank.
        item = self._item("totally unrelated text")
        ProductMatchingService().match_item(item, created_by=self.user)
        self.assertEqual(PendingProduct.objects.filter(boq_item=item).count(), 1)
        self.assertIsNone(ProductMatch.objects.get(boq_item=item).product)


class ConfidenceServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="c@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        self.pipe = RateMaster.objects.create(
            database_version=self.version,
            product_code="PIPE150",
            description="150 NB MS Pipe",
            make="Jindal",
            vendor="ACME",
            purchase_rate=1000,
        )
        boq = BOQ.objects.create(user=self.user, boq_name="B", uploaded_file="boq/x.xlsx")
        self.run = BOQRun.objects.create(boq=boq, run_number=1)

    def _match(self, *, reason, product, extraction=None, confidence=0):
        item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe", ai_extraction=extraction
        )
        return ProductMatch.objects.create(
            boq_item=item, product=product, confidence_score=confidence, match_reason=reason
        )

    def test_exact_match_stays_authoritative(self):
        match = self._match(reason="exact", product=self.pipe)
        score = ConfidenceService().evaluate(match)
        self.assertEqual(score, 100.0)
        self.assertEqual(band_for(score), "green")
        self.assertIn("exact match", match.ai_explanation)

    def test_no_match_scores_zero(self):
        match = self._match(reason="no_match", product=None)
        score = ConfidenceService().evaluate(match)
        self.assertEqual(score, 0.0)
        self.assertEqual(match.ai_explanation, "No matching product found.")

    @override_settings(OPENAI_API_KEY="placeholder-key")
    def test_alias_full_agreement_blends_high(self):
        match = self._match(
            reason="alias",
            product=self.pipe,
            extraction={"product": "pipe", "size": "150 NB", "material": "MS", "make": "Jindal"},
        )
        score = ConfidenceService().evaluate(match)
        self.assertEqual(score, 95.0)  # (90 base + 100 factors) / 2
        self.assertIn("agrees on", match.ai_explanation)

    def test_alias_partial_agreement_lowers_score(self):
        match = self._match(
            reason="alias",
            product=self.pipe,
            extraction={"product": "pipe", "make": "Tata"},  # make differs
        )
        score = ConfidenceService().evaluate(match)
        self.assertLess(score, 90.0)
        self.assertIn("differs on make", match.ai_explanation)

    @override_settings(OPENAI_API_KEY="sk-realLookingKey123")
    @mock.patch("apps.matching.services.confidence.AIService.run_json_prompt")
    def test_ai_validation_enriches_explanation(self, run_json_prompt):
        run_json_prompt.return_value = {"is_match": True, "confidence": 80, "reason": "sizes match"}
        match = self._match(reason="exact", product=self.pipe)
        score = ConfidenceService().evaluate(match)
        self.assertEqual(score, 90.0)  # (100 + 80) / 2
        self.assertIn("AI: sizes match", match.ai_explanation)

    def test_score_run_scores_all_matches(self):
        self._match(reason="exact", product=self.pipe)
        scored = ConfidenceService().score_run(self.run)
        self.assertEqual(scored, 1)


class VendorSelectionTests(TestCase):
    def setUp(self):
        self.modes = VendorSelectionMode
        self.user = get_user_model().objects.create_user(email="v@x.com", password="x")
        self.version = DatabaseVersion.objects.create(
            version_number=1, is_active=True, source_filename="db.xlsx"
        )
        # Three vendor rows for the same product_code at different prices/makes.
        self.jindal = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="Jindal", vendor="V1", purchase_rate=1200,
        )
        self.tata = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="Tata", vendor="V2", purchase_rate=1000,
        )
        self.apl = RateMaster.objects.create(
            database_version=self.version, product_code="PIPE150",
            description="150 NB MS Pipe", make="APL", vendor="V3", purchase_rate=800,
        )
        boq = BOQ.objects.create(user=self.user, boq_name="B", uploaded_file="boq/x.xlsx")
        self.run = BOQRun.objects.create(boq=boq, run_number=1)
        self.item = BOQItem.objects.create(
            boq_run=self.run, row_number=1, description="150 NB MS Pipe"
        )
        # Initial match points at the most expensive row.
        self.match = ProductMatch.objects.create(
            boq_item=self.item, product=self.jindal, confidence_score=100, match_reason="exact"
        )

    def _approve(self, *makes):
        for make in makes:
            MakeListEntry.objects.create(boq_run=self.run, make=make)

    def test_lowest_cost_picks_cheapest(self):
        chosen = VendorSelectionService(self.modes.LOWEST_COST).select_for_item(self.item)
        self.assertEqual(chosen, self.apl)
        self.match.refresh_from_db()
        self.assertEqual(self.match.vendor, "V3")
        self.assertEqual(self.match.make, "APL")

    def test_make_list_restricts_candidates(self):
        self._approve("Jindal", "Tata")  # APL (cheapest) excluded
        chosen = VendorSelectionService(self.modes.LOWEST_COST).select_for_item(self.item)
        self.assertEqual(chosen, self.tata)  # cheapest among approved

    def test_preferred_follows_make_list_order(self):
        self._approve("Tata", "APL")  # Tata preferred even though APL cheaper
        chosen = VendorSelectionService(self.modes.PREFERRED).select_for_item(self.item)
        self.assertEqual(chosen, self.tata)

    def test_custom_selection_uses_given_row(self):
        chosen = VendorSelectionService(self.modes.CUSTOM).select_for_item(
            self.item, custom_rate=self.jindal
        )
        self.assertEqual(chosen, self.jindal)

    def test_no_approved_vendor_returns_none(self):
        self._approve("Unknown Make")
        chosen = VendorSelectionService().select_for_item(self.item)
        self.assertIsNone(chosen)
        self.match.refresh_from_db()
        self.assertEqual(self.match.product, self.jindal)  # unchanged

    def test_select_run_counts_selected(self):
        selected = VendorSelectionService().select_run(self.run)
        self.assertEqual(selected, 1)
