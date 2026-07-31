"""Master database models.

Field names mirror workbook sheet columns. Each master row is scoped to the
``database_version`` that imported it; only the active version keeps rows in
PostgreSQL after import.

Ingested sheets (required): ``Rate_Master_Output``, ``Labour_master_Output``.
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


def product_display_key(
    category=None,
    sub_category=None,
    class_value=None,
    size=None,
    capacity=None,
    attribute=None,
) -> str:
    """UI composite: Category|Sub_Category|Class|Size|Capacity|Attribute."""

    def _part(value) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return text

    return "|".join(
        [
            _part(category),
            _part(sub_category),
            _part(class_value),
            _part(size),
            _part(capacity),
            _part(attribute),
        ]
    )


class Rate_Master_Output(models.Model):
    """Source: Rate_Master_Output sheet (one priced Make/Vendor row)."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="rate_master_output_rows",
    )
    # Workbook IDs are free-form codes ("P1001" as well as "1001"): store as text.
    Rate_ID = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    Product_ID = models.CharField(max_length=64, db_index=True)
    Category = models.CharField(max_length=255, null=True, blank=True)
    Sub_Category = models.CharField(max_length=255, null=True, blank=True)
    Class = models.CharField(max_length=255, null=True, blank=True)
    Size = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    Unit = models.CharField(max_length=100, null=True, blank=True)
    Capacity = models.CharField(max_length=255, null=True, blank=True)
    Attribute = models.TextField(null=True, blank=True)
    Make = models.CharField(max_length=255, null=True, blank=True)
    Vendor = models.CharField(max_length=255, null=True, blank=True)
    Base_Purchase_Rate = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Last_Updated = models.DateTimeField(null=True, blank=True)
    Discount = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True
    )
    Net_Material_Rate = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
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
    Sub_Total = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Profit_Value = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Final_Material_Amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    # Excel header: Margin_%_on_Selling
    Margin_pct_on_Selling = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        null=True,
        blank=True,
        db_column="Margin_pct_on_Selling",
    )

    class Meta:
        db_table = "Rate_Master_Output"
        indexes = [
            models.Index(fields=["database_version", "Product_ID"]),
            models.Index(fields=["database_version", "Rate_ID"]),
            models.Index(fields=["database_version", "Category", "Sub_Category"]),
        ]

    def display_key(self) -> str:
        return product_display_key(
            self.Category,
            self.Sub_Category,
            self.Class,
            self.Size,
            self.Capacity,
            self.Attribute,
        )

    def __str__(self) -> str:
        return f"Rate {self.Rate_ID} Product {self.Product_ID} {self.Make}/{self.Vendor}"


class Labour_master_Output(models.Model):
    """Source: Labour_master_Output sheet (one labour row per Product_ID)."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="labour_master_output_rows",
    )
    Product_ID = models.CharField(max_length=64, db_index=True)
    Category = models.CharField(max_length=255, null=True, blank=True)
    Sub_Category = models.CharField(max_length=255, null=True, blank=True)
    Class = models.CharField(max_length=255, null=True, blank=True)
    Size = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    Unit = models.CharField(max_length=100, null=True, blank=True)
    Capacity = models.CharField(max_length=255, null=True, blank=True)
    Attribute = models.TextField(null=True, blank=True)
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
    # Excel header keeps spaces: Total_Labour_per_unit_with _labour _Multipler
    Total_Labour_per_unit_with_labour_Multipler = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        db_column="Total_Labour_per_unit_with_labour_Multipler",
    )

    class Meta:
        db_table = "Labour_master_Output"
        indexes = [
            models.Index(fields=["database_version", "Product_ID"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["database_version", "Product_ID"],
                name="uniq_labour_product_per_version",
            )
        ]

    def display_key(self) -> str:
        return product_display_key(
            self.Category,
            self.Sub_Category,
            self.Class,
            self.Size,
            self.Capacity,
            self.Attribute,
        )

    def __str__(self) -> str:
        return f"Labour Product {self.Product_ID}"


# Master tables cleared for inactive versions after each import.
MASTER_DATA_MODELS = (
    Rate_Master_Output,
    Labour_master_Output,
)
