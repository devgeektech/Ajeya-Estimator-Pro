# Generated manually on 2026-07-09

from django.db import migrations


class Migration(migrations.Migration):
    """Drop the ProductEmbedding audit table.

    Chroma is the single source of the product vector index, so the PostgreSQL
    audit record is redundant. Idempotent so fresh installs (which no longer
    create the table) and already-migrated databases both succeed.
    """

    dependencies = [
        ("database_manager", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS database_manager_productembedding;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
