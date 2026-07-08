# Generated manually on 2026-07-08

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("boq", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE boq_boqitem
            ADD COLUMN IF NOT EXISTS target_excel_row integer NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
