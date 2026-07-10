"""Master database models.

Field names mirror workbook sheet columns (PascalCase). Each master row is
scoped to the ``database_version`` that imported it; only the active version
keeps rows in PostgreSQL after import.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models, transaction


class DatabaseVersion(models.Model):
    """Tracks an uploaded master database workbook."""

    version_number = models.PositiveIntegerField(unique=True)
    name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Custom name provided during upload",
    )
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
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="uniq_active_database_version",
            )
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_active:
                DatabaseVersion.objects.exclude(pk=self.pk).update(is_active=False)
            super().save(*args, **kwargs)

    def __str__(self) -> str:
        label = self.name or f"DB v{self.version_number}"
        return f"{label}{' (active)' if self.is_active else ''}"


class Rate_Master(models.Model):
    """Source: Rate_Master sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="rate_master_rows",
    )
    Category = models.CharField(max_length=255, null=True, blank=True)
    Sub_Category = models.CharField(max_length=255, null=True, blank=True)
    Class = models.CharField(max_length=255, null=True, blank=True)
    Size = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    Make = models.CharField(max_length=255, null=True, blank=True)
    Capacity = models.CharField(max_length=255, null=True, blank=True)
    Unit = models.CharField(max_length=100, null=True, blank=True)
    Attribute = models.TextField(null=True, blank=True)
    Supplier = models.CharField(max_length=255, null=True, blank=True)
    Base_Purchase_Rate = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Discount_Percent = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    Net_Material_Rate = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Tech_Key = models.CharField(max_length=255, db_index=True)
    Last_Updated = models.DateTimeField(null=True, blank=True)
    Procurement_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Commercial_Material_Base = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Accessories_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Handling_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Wastage_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Subtotal_Before_Profit = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Profit_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Final_Expenditure = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Final_Amount_Excl_GST = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Margin_Percent_On_Selling = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )

    class Meta:
        db_table = "Rate_Master"
        indexes = [models.Index(fields=["database_version", "Tech_Key"])]

    def __str__(self) -> str:
        return f"{self.Tech_Key} - {self.Make}"


class Labour_Master(models.Model):
    """Source: Labour_Master sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="labour_master_rows",
    )
    Tech_Key = models.CharField(max_length=255, db_index=True)
    Size = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    Labour_Type = models.CharField(max_length=255, null=True, blank=True)
    Base_Rate = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Size_Factor = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    Labour_Rate_Per_unit = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Testing_Labour_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Scaffolding_Labour_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Consumables_Labour_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Painting_Labour_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Labour_Buffer_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Total_Labour_per_Unit = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Labour_Multiplier = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    Total_Labour_per_unit_with_labour_Multipler = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )

    class Meta:
        db_table = "Labour_Master"

    def __str__(self) -> str:
        return self.Tech_Key or ""


class TOR_Main(models.Model):
    """Source: TOR_Main sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="tor_main_rows",
    )
    Category = models.CharField(max_length=255, null=True, blank=True)
    Handling_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    Wastage_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    Profit_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    Procurement_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    Risk_Buffer_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    Project_State = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "TOR_Main"

    def __str__(self) -> str:
        return self.Category or ""


class Labour_Structure_Source(models.Model):
    """Source: Labour_Structure_Source sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="labour_structure_rows",
    )
    Category = models.CharField(max_length=255, null=True, blank=True)
    Sub_Category = models.CharField(max_length=255, null=True, blank=True)
    Size = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    Unit = models.CharField(max_length=100, null=True, blank=True)
    Tech_Key = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "Labour_Structure_Source"

    def __str__(self) -> str:
        return self.Tech_Key or ""


class TOR_Labour(models.Model):
    """Source: TOR_Labour sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="tor_labour_rows",
    )
    Testing_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    Scaffolding_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    Consumables_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )
    Painting_Rate = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Labour_Buffer_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )

    class Meta:
        db_table = "TOR_Labour"


class TOR_Accessories(models.Model):
    """Source: TOR_Accessories sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="tor_accessories_rows",
    )
    Category = models.CharField(max_length=255, null=True, blank=True)
    Sub_Category = models.CharField(max_length=255, null=True, blank=True)
    Min_Size = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    Max_Size = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    Accessories_Percent = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True
    )

    class Meta:
        db_table = "TOR_Accessories"


class State_Control_List(models.Model):
    """Source: State_Control_List sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="state_control_rows",
    )
    State = models.CharField(max_length=255)
    Labour_Multiplier = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )

    class Meta:
        db_table = "State_Control_List"
        constraints = [
            models.UniqueConstraint(
                fields=["database_version", "State"],
                name="uniq_state_control_per_version",
            )
        ]

    def __str__(self) -> str:
        return self.State


# Master tables cleared for inactive versions after each import.
MASTER_DATA_MODELS = (
    Rate_Master,
    Labour_Master,
    TOR_Main,
    Labour_Structure_Source,
    TOR_Labour,
    TOR_Accessories,
    State_Control_List,
)
