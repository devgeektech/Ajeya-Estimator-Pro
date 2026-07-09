from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportfile",
            name="is_preview",
            field=models.BooleanField(
                default=False,
                help_text="Draft workbook generated before approval/export.",
            ),
        ),
    ]
