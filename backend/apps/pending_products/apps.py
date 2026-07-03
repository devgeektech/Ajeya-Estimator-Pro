from django.apps import AppConfig


class PendingProductsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pending_products"
    label = "pending_products"
    verbose_name = "Pending Products"
