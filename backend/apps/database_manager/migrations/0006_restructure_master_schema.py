# Generated manually for master schema restructure.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("database_manager", "0005_single_active_database_version"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="RateMaster",
            new_name="MaterialRate",
        ),
        migrations.AlterModelTable(
            name="materialrate",
            table="material_rate",
        ),
        migrations.RenameField(
            model_name="materialrate",
            old_name="product_class",
            new_name="material_class",
        ),
        migrations.RenameField(
            model_name="materialrate",
            old_name="size_mm",
            new_name="size",
        ),
        migrations.RenameField(
            model_name="materialrate",
            old_name="margin_percent_on_selling",
            new_name="margin_percent",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="accessories_percent",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="handling_percent",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="wastage_percent",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="profit_percent",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="status",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="procurement_percent",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="height",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="working_pressure",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="test_pressure",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="temperature",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="throw_distance",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="k_factor",
        ),
        migrations.RemoveField(
            model_name="materialrate",
            name="head",
        ),
        migrations.AddField(
            model_name="materialrate",
            name="attribute",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="category",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="sub_category",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="material_class",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="make",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="unit",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="base_purchase_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="discount_percent",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="net_material_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="tech_key",
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="procurement_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="commercial_material_base",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="accessories_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="handling_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="wastage_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="subtotal_before_profit",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="profit_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="final_expenditure",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="final_amount_excl_gst",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AlterField(
            model_name="materialrate",
            name="margin_percent",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True),
        ),
        migrations.RenameModel(
            old_name="TORMain",
            new_name="CategoryConfig",
        ),
        migrations.AlterModelTable(
            name="categoryconfig",
            table="category_config",
        ),
        migrations.AlterField(
            model_name="categoryconfig",
            name="category",
            field=models.CharField(db_index=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="categoryconfig",
            name="handling_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.AlterField(
            model_name="categoryconfig",
            name="wastage_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.AlterField(
            model_name="categoryconfig",
            name="profit_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.AlterField(
            model_name="categoryconfig",
            name="procurement_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.AlterField(
            model_name="categoryconfig",
            name="risk_buffer_percent",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=6, null=True),
        ),
        migrations.AddConstraint(
            model_name="categoryconfig",
            constraint=models.UniqueConstraint(
                fields=("database_version", "category"),
                name="uniq_category_config_per_version",
            ),
        ),
        migrations.RenameModel(
            old_name="TORLabour",
            new_name="LabourConfig",
        ),
        migrations.AlterModelTable(
            name="labourconfig",
            table="labour_config",
        ),
        migrations.AlterField(
            model_name="labourconfig",
            name="testing_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.AlterField(
            model_name="labourconfig",
            name="scaffolding_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.AlterField(
            model_name="labourconfig",
            name="consumables_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.AlterField(
            model_name="labourconfig",
            name="painting_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name="labourconfig",
            name="labour_buffer_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.RenameModel(
            old_name="TORAccessories",
            new_name="AccessoriesRule",
        ),
        migrations.AlterModelTable(
            name="accessoriesrule",
            table="accessories_rule",
        ),
        migrations.AlterField(
            model_name="accessoriesrule",
            name="min_size",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name="accessoriesrule",
            name="max_size",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name="accessoriesrule",
            name="accessories_percent",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.RenameModel(
            old_name="StateControl",
            new_name="StateMultiplier",
        ),
        migrations.AlterModelTable(
            name="statemultiplier",
            table="state_multiplier",
        ),
        migrations.AlterField(
            model_name="statemultiplier",
            name="state",
            field=models.CharField(db_index=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="statemultiplier",
            name="labour_multiplier",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=6),
        ),
        migrations.RemoveConstraint(
            model_name="statemultiplier",
            name="uniq_state_control_per_version",
        ),
        migrations.AddConstraint(
            model_name="statemultiplier",
            constraint=models.UniqueConstraint(
                fields=("database_version", "state"),
                name="uniq_state_multiplier_per_version",
            ),
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="category",
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="sub_category",
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="state",
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="unit",
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="testing_percent",
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="scaffolding_percent",
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="consumables_percent",
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="painting_rate",
        ),
        migrations.RemoveField(
            model_name="labourmaster",
            name="labour_buffer_percent",
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="size",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="labour_type",
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="size_factor",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="labour_multiplier",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=5),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="testing_labour_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="scaffolding_labour_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="consumables_labour_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="painting_labour_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="labour_buffer_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="total_labour_per_unit",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name="labourmaster",
            name="total_labour_with_multiplier",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterModelTable(
            name="labourmaster",
            table="labour_master",
        ),
        migrations.DeleteModel(
            name="LabourStructureSource",
        ),
    ]
