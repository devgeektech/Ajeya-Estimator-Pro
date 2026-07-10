# Generated manually on 2026-07-09

from django.db import migrations, models


def dedupe_active_database_versions(apps, schema_editor):
    DatabaseVersion = apps.get_model("database_manager", "DatabaseVersion")
    active_versions = list(
        DatabaseVersion.objects.filter(is_active=True).order_by(
            "-version_number", "-uploaded_at", "-pk"
        )
    )
    if len(active_versions) <= 1:
        return
    keep = active_versions[0]
    DatabaseVersion.objects.filter(is_active=True).exclude(pk=keep.pk).update(
        is_active=False
    )


class Migration(migrations.Migration):
    dependencies = [
        ("database_manager", "0004_prune_pending_products_migration_history"),
    ]

    operations = [
        migrations.RunPython(dedupe_active_database_versions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="databaseversion",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("is_active",),
                name="uniq_active_database_version",
            ),
        ),
    ]
