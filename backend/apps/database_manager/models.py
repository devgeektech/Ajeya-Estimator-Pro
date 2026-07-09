"""Master database + versioning models.

Schema sourced from docs/DATABASE_ARCHITECTURE.md (System, Master and
Product tables). The master workbook is imported per database version so
historical BOQs remain reproducible.
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
    tech_key = models.CharField(max_length=255, blank=True, db_index=True)
    make = models.CharField(max_length=150, blank=True)
    final_amount_excl_gst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit = models.CharField(max_length=50, blank=True)
    category = models.CharField(max_length=150, blank=True)
    sub_category = models.CharField(max_length=150, blank=True)
    product_class = models.CharField(max_length=100, blank=True, db_column="class")
    size_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    capacity = models.CharField(max_length=100, blank=True)
    height = models.CharField(max_length=50, blank=True)
    working_pressure = models.CharField(max_length=50, blank=True)
    test_pressure = models.CharField(max_length=50, blank=True)
    temperature = models.CharField(max_length=50, blank=True)
    throw_distance = models.CharField(max_length=50, blank=True)
    k_factor = models.CharField(max_length=50, blank=True)
    head = models.CharField(max_length=100, blank=True)
    supplier = models.CharField(max_length=150, blank=True)
    base_purchase_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    net_material_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    accessories_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    handling_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    wastage_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    profit_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    status = models.CharField(max_length=50, blank=True)
    last_updated = models.DateTimeField(null=True, blank=True)
    procurement_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    procurement_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commercial_material_base = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    accessories_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    handling_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    wastage_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    subtotal_before_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    final_expenditure = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    margin_percent_on_selling = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        indexes = [models.Index(fields=["database_version", "tech_key"])]

    def __str__(self) -> str:
        return f"{self.tech_key} - {self.make}"


class LabourMaster(models.Model):
    """Source: Labour_Master sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="labour_rates"
    )
    tech_key = models.CharField(max_length=255, blank=True, db_index=True)
    state = models.CharField(max_length=100, blank=True, db_index=True)
    category = models.CharField(max_length=100, blank=True)
    sub_category = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    labour_type = models.CharField(max_length=100, blank=True)
    base_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    size_factor = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    labour_rate_per_unit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    testing_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    scaffolding_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    consumables_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    painting_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    testing_labour_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    scaffolding_labour_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    consumables_labour_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    painting_labour_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    labour_buffer_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    labour_buffer_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_labour_per_unit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    labour_multiplier = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    total_labour_with_multiplier = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self) -> str:
        return self.tech_key


class TORMain(models.Model):
    """Source: TOR_Main sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_main"
    )
    category = models.CharField(max_length=100, blank=True, db_index=True)
    handling_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    wastage_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    profit_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    procurement_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    risk_buffer_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    project_state = models.CharField(max_length=100, blank=True)

    def __str__(self) -> str:
        return self.category


class LabourStructureSource(models.Model):
    """Source: Labour_Structure_Source sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="labour_structures"
    )
    category = models.CharField(max_length=100, blank=True)
    sub_category = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    tech_key = models.CharField(max_length=255, blank=True, db_index=True)

    def __str__(self) -> str:
        return self.tech_key


class TORLabour(models.Model):
    """Source: TOR_Labour sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_labour"
    )
    testing_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    scaffolding_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    consumables_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    painting_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    labour_buffer_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)


class TORAccessories(models.Model):
    """Source: TOR_Accessories sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_accessories"
    )
    category = models.CharField(max_length=100, blank=True)
    sub_category = models.CharField(max_length=100, blank=True)
    min_size = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_size = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    accessories_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)


class StateControl(models.Model):
    """Source: State_Control_List sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="state_controls"
    )
    state = models.CharField(max_length=150)
    labour_multiplier = models.DecimalField(max_digits=8, decimal_places=4, default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["database_version", "state"],
                name="uniq_state_control_per_version",
            )
        ]

    def __str__(self) -> str:
        return self.state
