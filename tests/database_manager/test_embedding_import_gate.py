"""Database import requires successful embeddings before activation."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.database_manager.models import DatabaseVersion, Product_Helper
from apps.database_manager.services.importer import DatabaseImportService
from common.choices import UserRole
from common.exceptions import AIServiceError, ImportError_

User = get_user_model()


class EmbeddingGatedImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )

    def _seed_inactive_version_with_helper(self) -> DatabaseVersion:
        version = DatabaseVersion.objects.create(
            version_number=1,
            name="Seed",
            uploaded_by=self.admin,
            source_filename="seed.xlsx",
            is_active=False,
        )
        Product_Helper.objects.create(
            database_version=version,
            Product_ID="P1",
            Category="Cat",
            Sub_Category="Sub",
            Class="1",
            Status="Active",
        )
        return version

    @override_settings(OPENAI_API_KEY="")
    def test_require_success_fails_without_openai_when_embeddable(self):
        from ai.embeddings.generator import generate_embeddings_for_version

        version = self._seed_inactive_version_with_helper()
        with self.assertRaises(AIServiceError):
            generate_embeddings_for_version(version.pk, require_success=True)

    @patch("ai.embeddings.generator.generate_embeddings_for_version")
    def test_importer_does_not_activate_when_embeddings_fail(self, mock_embed):
        mock_embed.side_effect = AIServiceError("boom")

        # Minimal stub: bypass workbook IO by calling the post-sheet path pieces
        # through a thin fake run that mirrors the real order.
        service = DatabaseImportService(
            file_path="unused.xlsx",
            uploaded_by=self.admin,
            source_filename="unused.xlsx",
            version_name="FailEmbed",
            stored_name="",
        )
        version = self._seed_inactive_version_with_helper()

        with self.assertRaises(ImportError_):
            service._generate_embeddings(version)

        version.refresh_from_db()
        self.assertFalse(version.is_active)
        mock_embed.assert_called_once_with(version.pk, require_success=True)

    @patch("ai.embeddings.generator.replace_embeddings_with_version")
    @patch("ai.embeddings.generator.generate_embeddings_for_version")
    def test_importer_activates_after_successful_embeddings(
        self, mock_embed, mock_replace
    ):
        mock_embed.return_value = {
            "total": 1,
            "generated": 1,
            "skipped": 0,
            "errors": 0,
            "embeddable": 1,
        }
        service = DatabaseImportService(
            file_path="unused.xlsx",
            uploaded_by=self.admin,
            source_filename="unused.xlsx",
            version_name="OkEmbed",
            stored_name="",
        )
        version = self._seed_inactive_version_with_helper()
        service._generate_embeddings(version)
        service._activate(version)
        service._replace_chroma_with_active(version)

        version.refresh_from_db()
        self.assertTrue(version.is_active)
        mock_embed.assert_called_once_with(version.pk, require_success=True)
        mock_replace.assert_called_once_with(version.pk)

    def test_importer_surfaces_credits_message_without_wrapping(self):
        from ai.errors import AI_CREDITS_EMPTY_MESSAGE

        service = DatabaseImportService(
            file_path="unused.xlsx",
            uploaded_by=self.admin,
            source_filename="unused.xlsx",
            version_name="FailQuota",
            stored_name="",
        )
        version = self._seed_inactive_version_with_helper()

        with patch(
            "ai.embeddings.generator.generate_embeddings_for_version",
            side_effect=AIServiceError(AI_CREDITS_EMPTY_MESSAGE),
        ):
            with self.assertRaises(ImportError_) as ctx:
                service._generate_embeddings(version)

        self.assertEqual(str(ctx.exception), AI_CREDITS_EMPTY_MESSAGE)

    @override_settings(
        OPENAI_API_KEY="sk-test-quota-abort-key",
        OPENAI_EMBEDDING_BATCH_SIZE=1,
    )
    @patch("ai.embeddings.generator.ChromaEmbeddingStore")
    @patch("ai.embeddings.generator.generate_embeddings")
    def test_quota_stops_remaining_helper_batches(self, mock_embed, mock_store_cls):
        from ai.embeddings.generator import generate_embeddings_for_version
        from ai.errors import AI_CREDITS_EMPTY_MESSAGE

        mock_embed.side_effect = AIServiceError(AI_CREDITS_EMPTY_MESSAGE)
        store = mock_store_cls.return_value
        version = self._seed_inactive_version_with_helper()
        Product_Helper.objects.create(
            database_version=version,
            Product_ID="P2",
            Category="Cat",
            Sub_Category="Sub",
            Class="1",
            Status="Active",
        )
        Product_Helper.objects.create(
            database_version=version,
            Product_ID="P3",
            Category="Cat",
            Sub_Category="Sub",
            Class="1",
            Status="Active",
        )

        with self.assertRaises(AIServiceError) as ctx:
            generate_embeddings_for_version(version.pk, require_success=True)

        self.assertEqual(str(ctx.exception), AI_CREDITS_EMPTY_MESSAGE)
        self.assertEqual(mock_embed.call_count, 1)
        self.assertGreaterEqual(store.reset_version.call_count, 1)
