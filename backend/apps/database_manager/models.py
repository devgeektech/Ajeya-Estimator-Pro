"""Master database models.

Field names mirror workbook sheet columns. Each master row is scoped to the
``database_version`` that imported it; only the active version keeps rows in
PostgreSQL after import.

Ingested sheets (required): ``Product_Helper``, ``Rate_Master_Output``,
``Labour_Master_Output`` (older workbooks may still use ``Labour_master_Output``;
``Product_Master`` is accepted as an alias for ``Product_Helper``).

Instance attributes are annotated with Python value types so basedpyright treats
them as data rather than Field descriptors (``# type: ignore[assignment]``).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import Manager

from common.db import atomic


class DatabaseVersion(models.Model):
    """Tracks an uploaded master database workbook."""

    objects: ClassVar[Manager[DatabaseVersion]] = models.Manager()
    pk: int

    version_number: int = models.PositiveIntegerField(unique=True)  # type: ignore[assignment]
    name: str = models.CharField(  # type: ignore[assignment]
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
    uploaded_at: datetime = models.DateTimeField(auto_now_add=True)  # type: ignore[assignment]
    is_active: bool = models.BooleanField(default=False)  # type: ignore[assignment]
    file = models.FileField(upload_to="database/", null=True, blank=True)
    source_filename: str = models.CharField(max_length=255)  # type: ignore[assignment]

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
        with atomic():
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
    unit=None,
    capacity=None,
    attribute=None,
) -> str:
    """UI composite: Category|Sub_Category|Class|Size|Unit|Capacity|Attribute."""

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
            _part(unit),
            _part(capacity),
            _part(attribute),
        ]
    )


class Product_Helper(models.Model):
    """Source: Product_Helper sheet (one catalog product identity per Product_ID).

    Make/Vendor prices live on ``Rate_Master_Output`` rows that share this
    ``Product_ID``. Labour joins on the same ``Product_ID``.
    """

    objects: ClassVar[Manager[Product_Helper]] = models.Manager()

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="product_helper_rows",
    )
    Product_ID: str = models.CharField(max_length=64, db_index=True)  # type: ignore[assignment]
    Category: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Sub_Category: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Class: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Size: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    Unit: str | None = models.CharField(  # type: ignore[assignment]
        max_length=100, null=True, blank=True
    )
    Capacity: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Attribute: str | None = models.TextField(null=True, blank=True)  # type: ignore[assignment]
    Status: str | None = models.CharField(  # type: ignore[assignment]
        max_length=64, null=True, blank=True
    )

    class Meta:
        db_table = "Product_Helper"
        indexes = [
            models.Index(fields=["database_version", "Product_ID"]),
            models.Index(fields=["database_version", "Category", "Sub_Category"]),
        ]

    def display_key(self) -> str:
        return product_display_key(
            self.Category,
            self.Sub_Category,
            self.Class,
            self.Size,
            self.Unit,
            self.Capacity,
            self.Attribute,
        )

    def __str__(self) -> str:
        return f"Product {self.Product_ID} {self.display_key()}"


class Rate_Master_Output(models.Model):
    """Source: Rate_Master_Output sheet (one priced Make/Vendor row)."""

    objects: ClassVar[Manager[Rate_Master_Output]] = models.Manager()

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="rate_master_output_rows",
    )
    # Workbook IDs are free-form codes ("P1001" as well as "1001"): store as text.
    Rate_ID: str | None = models.CharField(  # type: ignore[assignment]
        max_length=64, null=True, blank=True, db_index=True
    )
    Product_ID: str = models.CharField(max_length=64, db_index=True)  # type: ignore[assignment]
    Category: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Sub_Category: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Class: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Size: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    Unit: str | None = models.CharField(  # type: ignore[assignment]
        max_length=100, null=True, blank=True
    )
    Capacity: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Attribute: str | None = models.TextField(null=True, blank=True)  # type: ignore[assignment]
    Make: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Vendor: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Base_Purchase_Rate: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Last_Updated: datetime | None = models.DateTimeField(  # type: ignore[assignment]
        null=True, blank=True
    )
    Discount: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=6, null=True, blank=True
    )
    Net_Material_Rate: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Procurement_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Commercial_Material_Base: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Accessories_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Handling_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Wastage_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Sub_Total: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Profit_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Final_Material_Amount: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    # Excel header: Margin_%_on_Selling
    Margin_pct_on_Selling: Decimal | None = models.DecimalField(  # type: ignore[assignment]
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
            self.Unit,
            self.Capacity,
            self.Attribute,
        )

    def __str__(self) -> str:
        return f"Rate {self.Rate_ID} Product {self.Product_ID} {self.Make}/{self.Vendor}"


class Labour_master_Output(models.Model):
    """Source: Labour_Master_Output sheet (one labour row per Product_ID).

    PostgreSQL table name remains ``Labour_master_Output``. The preferred
    workbook sheet title is ``Labour_Master_Output``; older files may use
    ``Labour_master_Output``. Column ``Labour_With_State_Multiplier`` maps into
    ``Total_Labour_per_unit_with_labour_Multipler``.
    """

    objects: ClassVar[Manager[Labour_master_Output]] = models.Manager()

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="labour_master_output_rows",
    )
    Product_ID: str = models.CharField(max_length=64, db_index=True)  # type: ignore[assignment]
    Category: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Sub_Category: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Class: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Size: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    Unit: str | None = models.CharField(  # type: ignore[assignment]
        max_length=100, null=True, blank=True
    )
    Capacity: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Attribute: str | None = models.TextField(null=True, blank=True)  # type: ignore[assignment]
    Labour_Type: str | None = models.CharField(  # type: ignore[assignment]
        max_length=255, null=True, blank=True
    )
    Base_Rate: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Size_Factor: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    Labour_Rate_Per_unit: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Testing_Labour_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Scaffolding_Labour_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Consumables_Labour_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Painting_Labour_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Labour_Buffer_Value: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    Total_Labour_per_Unit: Decimal | None = models.DecimalField(  # type: ignore[assignment]
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    # Excel header keeps spaces: Total_Labour_per_unit_with _labour _Multipler
    Total_Labour_per_unit_with_labour_Multipler: Decimal | None = models.DecimalField(  # type: ignore[assignment]
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
            self.Unit,
            self.Capacity,
            self.Attribute,
        )

    def __str__(self) -> str:
        return f"Labour Product {self.Product_ID}"


# Master tables cleared for inactive versions after each import.
MASTER_DATA_MODELS = (
    Product_Helper,
    Rate_Master_Output,
    Labour_master_Output,
)
