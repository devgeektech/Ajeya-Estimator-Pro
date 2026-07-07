from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("database_manager", "0004_databaseversion_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="ratemaster",
            name="final_amount_excl_gst",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
    ]
