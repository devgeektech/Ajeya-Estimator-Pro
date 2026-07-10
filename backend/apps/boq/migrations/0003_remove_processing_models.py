# Generated manually — remove BOQ processing models; upload-only BOQ retained.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("boq", "0002_repair_target_excel_row_column"),
    ]

    operations = [
        migrations.DeleteModel(
            name="BOQItem",
        ),
        migrations.DeleteModel(
            name="BOQRun",
        ),
    ]
