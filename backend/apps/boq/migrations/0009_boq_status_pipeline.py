# Generated manually for status pipeline (Make/Vendor → Ready to Export → Exported)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boq", "0008_boq_matching_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="boq",
            name="status",
            field=models.CharField(
                choices=[
                    ("UPLOADED", "Uploaded"),
                    ("PROCESSING", "Analysing..."),
                    ("EXTRACTED", "Analysed"),
                    ("MAKE_VENDOR", "Make/Vendor selection"),
                    ("MATCHING", "Matching"),
                    ("PROCESSED", "Matched"),
                    ("READY_EXPORT", "Ready to Export"),
                    ("EXPORTED", "Exported"),
                    ("ANALYSIS_FAILED", "Analysis Failed"),
                ],
                default="UPLOADED",
                max_length=20,
            ),
        ),
    ]
