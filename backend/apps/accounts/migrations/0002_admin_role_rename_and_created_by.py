"""
Migration: rename role 'SUPER_ADMIN' → 'ADMIN' + add created_by FK.

- Updates the role choices (AlterField) to reflect the new ADMIN value.
- Runs a RunPython step to convert all existing 'SUPER_ADMIN' rows in the
  accounts_user table to 'ADMIN'.
- Adds the created_by FK (nullable self-reference).
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def rename_super_admin_to_admin(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="SUPER_ADMIN").update(role="ADMIN")


def reverse_admin_to_super_admin(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="ADMIN").update(role="SUPER_ADMIN")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        # 1. Add created_by FK first (nullable — no constraint issues).
        migrations.AddField(
            model_name="user",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_users",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 2. Update the role field choices to include ADMIN (DB-level: varchar, no enum).
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[("ADMIN", "Admin"), ("EXPERT", "Expert")],
                default="EXPERT",
                max_length=20,
            ),
        ),
        # 3. Convert existing data: SUPER_ADMIN → ADMIN.
        migrations.RunPython(
            rename_super_admin_to_admin,
            reverse_code=reverse_admin_to_super_admin,
        ),
    ]
