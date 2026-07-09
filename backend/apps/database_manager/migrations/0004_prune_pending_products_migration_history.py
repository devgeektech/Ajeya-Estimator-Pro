# Generated manually on 2026-07-09

from django.db import migrations


class Migration(migrations.Migration):
    """Remove orphaned pending_products migration history after app deletion."""

    dependencies = [
        ("database_manager", "0003_version_statecontrol_remove_productalias"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DELETE FROM django_migrations
            WHERE app = 'pending_products';

            DROP TABLE IF EXISTS pending_products_pendingproduct;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
