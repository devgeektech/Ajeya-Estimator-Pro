# Prune migration history and drop tables for removed BOQ pipeline apps.

from django.db import migrations


def prune_removed_apps(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM django_migrations
            WHERE app IN (
                'processing',
                'matching',
                'costing',
                'review',
                'exports',
                'make_list'
            );
            """
        )
        cursor.execute("DROP TABLE IF EXISTS costing_ratedetail CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS matching_productmatch CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS matching_activitymatch CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS processing_processingjob CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS review_reviewitem CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS exports_exportfile CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS make_list_makelistentry CASCADE;")


class Migration(migrations.Migration):

    dependencies = [
        ("database_manager", "0009_allow_null_master_fields"),
        ("boq", "0003_remove_processing_models"),
    ]

    operations = [
        migrations.RunPython(prune_removed_apps, migrations.RunPython.noop),
    ]
