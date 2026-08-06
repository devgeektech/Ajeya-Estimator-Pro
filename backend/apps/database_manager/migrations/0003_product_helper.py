# Generated manually for Product_Helper catalog sheet.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("database_manager", "0002_alter_labour_master_output_product_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Product_Helper",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("Product_ID", models.CharField(db_index=True, max_length=64)),
                ("Category", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "Sub_Category",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("Class", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "Size",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=12, null=True
                    ),
                ),
                ("Unit", models.CharField(blank=True, max_length=100, null=True)),
                ("Capacity", models.CharField(blank=True, max_length=255, null=True)),
                ("Attribute", models.TextField(blank=True, null=True)),
                ("Status", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "database_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="product_helper_rows",
                        to="database_manager.databaseversion",
                    ),
                ),
            ],
            options={
                "db_table": "Product_Helper",
            },
        ),
        migrations.AddIndex(
            model_name="product_helper",
            index=models.Index(
                fields=["database_version", "Product_ID"],
                name="Product_Hel_databas_7c1a2b_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="product_helper",
            index=models.Index(
                fields=["database_version", "Category", "Sub_Category"],
                name="Product_Hel_databas_9d4e3f_idx",
            ),
        ),
    ]
