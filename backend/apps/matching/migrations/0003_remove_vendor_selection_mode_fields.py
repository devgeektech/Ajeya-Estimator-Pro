from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("matching", "0002_productmatch_custom_maker_productmatch_vendor_mode"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="productmatch",
            name="custom_maker",
        ),
        migrations.RemoveField(
            model_name="productmatch",
            name="vendor_mode",
        ),
    ]
