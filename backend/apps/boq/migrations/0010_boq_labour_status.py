# Add LABOUR status for Make & Vendor → Labour → Review pipeline.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boq", "0009_boq_status_pipeline"),
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
                    ("LABOUR", "Labour"),
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
