from django.apps import AppConfig


class DatabaseManagerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.database_manager"
    label = "database_manager"
    verbose_name = "Database Manager"
