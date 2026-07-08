# Generated manually on 2026-07-08

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("matching", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE matching_productmatch
            ADD COLUMN IF NOT EXISTS match_type varchar(50) NOT NULL DEFAULT '';

            ALTER TABLE matching_productmatch
            ADD COLUMN IF NOT EXISTS product_quantity numeric(14, 4) NOT NULL DEFAULT 1;

            ALTER TABLE matching_productmatch
            ADD COLUMN IF NOT EXISTS product_unit varchar(50) NOT NULL DEFAULT '';

            ALTER TABLE matching_productmatch
            ADD COLUMN IF NOT EXISTS quantity_basis varchar(50) NOT NULL DEFAULT 'unknown';

            ALTER TABLE matching_productmatch
            ADD COLUMN IF NOT EXISTS quantity_source varchar(50) NOT NULL DEFAULT '';

            ALTER TABLE matching_productmatch
            ADD COLUMN IF NOT EXISTS review_required boolean NOT NULL DEFAULT false;

            ALTER TABLE matching_productmatch ALTER COLUMN match_type DROP DEFAULT;
            ALTER TABLE matching_productmatch ALTER COLUMN product_quantity DROP DEFAULT;
            ALTER TABLE matching_productmatch ALTER COLUMN product_unit DROP DEFAULT;
            ALTER TABLE matching_productmatch ALTER COLUMN quantity_basis DROP DEFAULT;
            ALTER TABLE matching_productmatch ALTER COLUMN quantity_source DROP DEFAULT;
            ALTER TABLE matching_productmatch ALTER COLUMN review_required DROP DEFAULT;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
