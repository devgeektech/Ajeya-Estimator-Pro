# Generated manually on 2026-07-08

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("costing", "0002_repair_ratedetail_table"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'costing_costbreakdown'
                ) AND EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'costing_costbreakdow_product_match_id_554e066b_fk_matching_'
                ) THEN
                    ALTER TABLE costing_costbreakdown
                    DROP CONSTRAINT costing_costbreakdow_product_match_id_554e066b_fk_matching_;

                    ALTER TABLE costing_costbreakdown
                    ADD CONSTRAINT costing_costbreakdow_product_match_id_554e066b_fk_matching_
                    FOREIGN KEY (product_match_id)
                    REFERENCES matching_productmatch(id)
                    ON DELETE CASCADE
                    DEFERRABLE INITIALLY DEFERRED;
                END IF;
            END
            $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
