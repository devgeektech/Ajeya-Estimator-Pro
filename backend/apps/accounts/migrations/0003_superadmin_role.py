from django.db import migrations, models


def mark_superusers_as_superadmin(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_superuser=True).update(role="SUPERADMIN")


def reverse_superadmins_to_admin(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="SUPERADMIN").update(role="ADMIN")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_admin_role_rename_and_created_by"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("SUPERADMIN", "Superadmin"),
                    ("ADMIN", "Admin"),
                    ("EXPERT", "Expert"),
                ],
                default="EXPERT",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            mark_superusers_as_superadmin,
            reverse_code=reverse_superadmins_to_admin,
        ),
    ]
