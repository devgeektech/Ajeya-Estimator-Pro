"""Keep only the newest 10 database uploads; drop oldest workbook files."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from apps.database_manager.models import DatabaseVersion, Product_Helper
from apps.database_manager.services.activation import (
    enforce_version_retention,
    purge_inactive_master_data,
)
from apps.database_manager.services.importer import DatabaseImportService
from common.choices import UserRole
from common.constants import DATABASE_UPLOADS_TO_RETAIN

User = get_user_model()


class DatabaseRetentionTests(TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="db_retain_")
        self._media = Path(self._tmpdir)
        self._override = override_settings(MEDIA_ROOT=str(self._media))
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(lambda: shutil.rmtree(self._tmpdir, ignore_errors=True))

        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="password",
            role=UserRole.ADMIN,
            is_staff=True,
        )

    def _create_version(self, number: int, *, active: bool = False) -> DatabaseVersion:
        version = DatabaseVersion(
            version_number=number,
            name=f"DB {number}",
            uploaded_by=self.admin,
            source_filename=f"db_{number}.xlsx",
            is_active=active,
        )
        version.file.save(
            f"db_{number}.xlsx",
            ContentFile(b"PK\x03\x04fake"),
            save=False,
        )
        version.save()
        return version

    def test_eleventh_success_deletes_oldest_record_and_media_file(self):
        versions = [self._create_version(i, active=(i == 10)) for i in range(1, 11)]
        oldest = versions[0]
        oldest_path = Path(oldest.file.path)
        self.assertTrue(oldest_path.is_file())

        newest = self._create_version(11, active=True)
        DatabaseVersion.objects.filter(pk=oldest.pk).update(is_active=False)
        # Mirror post-import success path: purge inactive PG rows, then retain.
        Product_Helper.objects.create(
            database_version=newest,
            Product_ID="P1",
            Category="Cat",
            Sub_Category="Sub",
            Class="1",
            Status="Active",
        )
        with patch("ai.embeddings.chroma_store.ChromaEmbeddingStore.reset_version"):
            purge_inactive_master_data(newest)
        removed = enforce_version_retention()

        self.assertEqual(removed, 1)
        self.assertEqual(DatabaseVersion.objects.count(), DATABASE_UPLOADS_TO_RETAIN)
        self.assertFalse(DatabaseVersion.objects.filter(version_number=1).exists())
        self.assertTrue(DatabaseVersion.objects.filter(version_number=11).exists())
        self.assertFalse(oldest_path.exists())
        self.assertTrue(Path(newest.file.path).exists())

    def test_retention_noop_when_at_or_under_limit(self):
        for i in range(1, DATABASE_UPLOADS_TO_RETAIN + 1):
            self._create_version(i, active=(i == DATABASE_UPLOADS_TO_RETAIN))
        self.assertEqual(enforce_version_retention(), 0)
        self.assertEqual(DatabaseVersion.objects.count(), DATABASE_UPLOADS_TO_RETAIN)

    @patch("ai.embeddings.generator.replace_embeddings_with_version")
    @patch("ai.embeddings.generator.generate_embeddings_for_version")
    def test_importer_calls_retention_only_after_success(
        self, mock_embed, mock_replace
    ):
        mock_embed.return_value = {
            "total": 0,
            "generated": 0,
            "skipped": 0,
            "errors": 0,
            "embeddable": 0,
        }
        for i in range(1, 11):
            self._create_version(i, active=(i == 10))

        service = DatabaseImportService(
            file_path="unused.xlsx",
            uploaded_by=self.admin,
            source_filename="v11.xlsx",
            version_name="V11",
            stored_name="database/v11.xlsx",
        )
        # Create the new inactive version + helper the way run() would mid-flight.
        version = self._create_version(11, active=False)
        Product_Helper.objects.create(
            database_version=version,
            Product_ID="P11",
            Category="Cat",
            Sub_Category="Sub",
            Class="1",
            Status="Active",
        )

        with patch.object(service, "_create_version", return_value=version), patch.object(
            service, "_import_versioned_sheets"
        ), patch(
            "apps.database_manager.services.importer.validate_workbook"
        ), patch(
            "ai.embeddings.chroma_store.ChromaEmbeddingStore.reset_version"
        ):
            # Point stored file so retention has something to delete for v1.
            result = service.run()

        self.assertEqual(result.pk, version.pk)
        self.assertTrue(result.is_active)
        self.assertFalse(DatabaseVersion.objects.filter(version_number=1).exists())
        self.assertEqual(DatabaseVersion.objects.count(), DATABASE_UPLOADS_TO_RETAIN)
        mock_embed.assert_called()
        mock_replace.assert_called_once_with(version.pk)
