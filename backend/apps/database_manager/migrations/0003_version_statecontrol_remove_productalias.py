# Generated manually on 2026-07-09

from django.db import migrations


def assign_state_control_versions(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE database_manager_statecontrol sc
            SET database_version_id = dv.id
            FROM database_manager_databaseversion dv
            WHERE sc.database_version_id IS NULL
              AND dv.is_active = true;
            """
        )
        cursor.execute(
            """
            UPDATE database_manager_statecontrol sc
            SET database_version_id = dv.id
            FROM (
                SELECT id
                FROM database_manager_databaseversion
                ORDER BY version_number DESC
                LIMIT 1
            ) dv
            WHERE sc.database_version_id IS NULL;
            """
        )
        cursor.execute(
            """
            DELETE FROM database_manager_statecontrol
            WHERE database_version_id IS NULL;
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("database_manager", "0002_remove_productembedding"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE database_manager_statecontrol
                ADD COLUMN IF NOT EXISTS database_version_id bigint;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(assign_state_control_versions, migrations.RunPython.noop),
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'database_manager_statecontrol_state_key'
                ) THEN
                    ALTER TABLE database_manager_statecontrol
                    DROP CONSTRAINT database_manager_statecontrol_state_key;
                END IF;
            END
            $$;

            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'database_manager_statecontrol'
                      AND column_name = 'database_version_id'
                      AND is_nullable = 'YES'
                ) THEN
                    ALTER TABLE database_manager_statecontrol
                    ALTER COLUMN database_version_id SET NOT NULL;
                END IF;
            END
            $$;

            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'database_manager_statecontrol_database_version_id_fk'
                ) THEN
                    ALTER TABLE database_manager_statecontrol
                    ADD CONSTRAINT database_manager_statecontrol_database_version_id_fk
                    FOREIGN KEY (database_version_id)
                    REFERENCES database_manager_databaseversion(id)
                    DEFERRABLE INITIALLY DEFERRED;
                END IF;
            END
            $$;

            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'uniq_state_control_per_version'
                ) THEN
                    ALTER TABLE database_manager_statecontrol
                    ADD CONSTRAINT uniq_state_control_per_version
                    UNIQUE (database_version_id, state);
                END IF;
            END
            $$;

            DROP TABLE IF EXISTS database_manager_productalias;
            DROP TABLE IF EXISTS pending_products_pendingproduct;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
