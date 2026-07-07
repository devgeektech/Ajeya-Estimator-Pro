"""Master database + versioning models.

Schema sourced from docs/DATABASE_ARCHITECTURE.md (System, Master and
Product tables). The master workbook is imported per database version so
historical BOQs remain reproducible.

Note: ProductEmbedding.embedding_vector is stored as JSON for V1 so vectors can
be stored without extra database extensions.
"""
from django.conf import settings
from django.db import models


class DatabaseVersion(models.Model):
    """Tracks an uploaded master database workbook."""

    version_number = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255, blank=True, help_text="Custom name provided during upload")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="database_versions",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=False)
    file = models.FileField(upload_to="database/", null=True, blank=True)
    source_filename = models.CharField(max_length=255)

    class Meta:
        ordering = ["-version_number"]

    def __str__(self) -> str:
        active = " (active)" if self.is_active else ""
        return f"{self.name or f'DB v{self.version_number}'}{active}"


class RateMaster(models.Model):
    """Source: Rate_Master sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="rates"
    )
    product_code = models.CharField(max_length=100, db_index=True)
    description = models.TextField()
    make = models.CharField(max_length=150, blank=True)
    vendor = models.CharField(max_length=150, blank=True)
    purchase_rate = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    final_amount_excl_gst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit = models.CharField(max_length=50, blank=True)
    category = models.CharField(max_length=150, blank=True)
    subcategory = models.CharField(max_length=150, blank=True)
    remarks = models.TextField(blank=True)
    # Extra columns / evolving schema mapping (flexible V1 design).
    spec_json = models.JSONField(default=dict, blank=True, help_text="All raw Excel columns stored as key-value pairs.")

    class Meta:
        indexes = [models.Index(fields=["database_version", "product_code"])]

    def __str__(self) -> str:
        return f"{self.product_code} - {self.make}"


class LabourMaster(models.Model):
    """Source: Labour_Master sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="labour_rates"
    )
    labour_code = models.CharField(max_length=100, db_index=True)
    labour_name = models.CharField(max_length=255)
    labour_rate = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit = models.CharField(max_length=50, blank=True)
    # Extra columns / evolving schema mapping (flexible V1 design).
    spec_json = models.JSONField(default=dict, blank=True, help_text="All raw Excel columns stored as key-value pairs.")

    def __str__(self) -> str:
        return self.labour_code


class TORMain(models.Model):
    """Source: TOR_Main sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_main"
    )
    tor_code = models.CharField(max_length=100, db_index=True)
    description = models.TextField(blank=True)
    spec_json = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.tor_code


class TORLabour(models.Model):
    """Source: TOR_Labour sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_labour"
    )
    tor_code = models.CharField(max_length=100, db_index=True)
    labour_code = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    spec_json = models.JSONField(default=dict, blank=True)


class TORAccessories(models.Model):
    """Source: TOR_Accessories sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_accessories"
    )
    tor_code = models.CharField(max_length=100, db_index=True)
    accessory_code = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    spec_json = models.JSONField(default=dict, blank=True)


class StateControl(models.Model):
    """Source: State_Control_List sheet."""

    state_name = models.CharField(max_length=150, unique=True)
    labour_multiplier = models.DecimalField(max_digits=8, decimal_places=4, default=1)
    transportation_multiplier = models.DecimalField(
        max_digits=8, decimal_places=4, default=1
    )

    def __str__(self) -> str:
        return self.state_name


class ProductAlias(models.Model):
    """Alternative product descriptions (e.g. '150 NB Pipe', 'ERW Pipe')."""

    alias = models.CharField(max_length=255, db_index=True)
    product_code = models.CharField(max_length=100, db_index=True)

    class Meta:
        verbose_name_plural = "Product aliases"

    def __str__(self) -> str:
        return f"{self.alias} -> {self.product_code}"


class ProductEmbedding(models.Model):
    """Vector embedding for AI-assisted product search.

    Stored as JSON in V1; migrates to pgvector in the AI sprint.
    """

    product_code = models.CharField(max_length=100, db_index=True)
    embedding_vector = models.JSONField(default=list)
    generated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Embedding({self.product_code})"
