# Repair Labour_Structure_Source columns after workbook alignment.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("database_manager", "0007_align_workbook_schema"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'Labour_Structure_Source'
                      AND column_name = 'Sub category'
                ) THEN
                    ALTER TABLE "Labour_Structure_Source"
                    RENAME COLUMN "Sub category" TO "Sub_Category";
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'Labour_Structure_Source'
                      AND column_name = 'Sub_category'
                ) THEN
                    ALTER TABLE "Labour_Structure_Source"
                    RENAME COLUMN "Sub_category" TO "Sub_Category";
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'Labour_Structure_Source'
                      AND column_name = 'Size '
                ) THEN
                    ALTER TABLE "Labour_Structure_Source"
                    RENAME COLUMN "Size " TO "Size";
                END IF;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="labour_structure_source",
            name="Sub_Category",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
