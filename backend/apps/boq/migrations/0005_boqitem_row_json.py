from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boq", "0004_boqrun_original_headers"),
    ]

    operations = [
        migrations.AddField(
            model_name="boqitem",
            name="row_json",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
