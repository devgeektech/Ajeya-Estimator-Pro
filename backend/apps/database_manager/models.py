"""Master database models.

Schema mirrors the client workbook sheet columns (PascalCase field names with
``db_column`` headers). ``database_version`` scopes every master row to the
upload that imported it.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models, transaction


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
        active = " (active)" if self.is_active else ""
        return f"{self.name or f'DB v{self.version_number}'}{active}"


class Rate_Master(models.Model):
    """Source: Rate_Master sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="rate_master_rows"
    )
    Category = models.CharField(max_length=255, null=True, blank=True)
    Sub_Category = models.CharField(max_length=255, null=True, blank=True)
    Class = models.CharField(max_length=255, null=True, blank=True)
    Size = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
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

    _KW_ALIASES = {
        "tech_key": "Tech_Key",
        "category": "Category",
        "sub_category": "Sub_Category",
        "material_class": "Class",
        "class": "Class",
        "product_class": "Class",
        "size": "Size",
        "size_mm": "Size",
        "make": "Make",
        "capacity": "Capacity",
        "unit": "Unit",
        "attribute": "Attribute",
        "supplier": "Supplier",
        "base_purchase_rate": "Base_Purchase_Rate",
        "discount_percent": "Discount_Percent",
        "net_material_rate": "Net_Material_Rate",
        "procurement_value": "Procurement_Value",
        "commercial_material_base": "Commercial_Material_Base",
        "accessories_value": "Accessories_Value",
        "handling_value": "Handling_Value",
        "wastage_value": "Wastage_Value",
        "subtotal_before_profit": "Subtotal_Before_Profit",
        "profit_value": "Profit_Value",
        "final_expenditure": "Final_Expenditure",
        "final_amount_excl_gst": "Final_Amount_Excl_GST",
        "margin_percent": "Margin_Percent_On_Selling",
        "margin_percent_on_selling": "Margin_Percent_On_Selling",
    }

    def __init__(self, *args, **kwargs):
        for alias, field in self._KW_ALIASES.items():
            if alias in kwargs:
                kwargs[field] = kwargs.pop(alias)
        super().__init__(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.Tech_Key} - {self.Make}"

    @property
    def tech_key(self) -> str:
        return self.Tech_Key or ""

    @tech_key.setter
    def tech_key(self, value: str) -> None:
        self.Tech_Key = value

    @property
    def category(self) -> str:
        return self.Category or ""

    @category.setter
    def category(self, value: str) -> None:
        self.Category = value

    @property
    def sub_category(self) -> str:
        return self.Sub_Category or ""

    @sub_category.setter
    def sub_category(self, value: str) -> None:
        self.Sub_Category = value

    @property
    def material_class(self) -> str:
        return self.Class or ""

    @material_class.setter
    def material_class(self, value: str) -> None:
        self.Class = value

    @property
    def product_class(self) -> str:
        return self.material_class

    @property
    def size(self):
        return self.Size

    @size.setter
    def size(self, value) -> None:
        self.Size = value

    @property
    def size_mm(self):
        return self.Size

    @property
    def make(self) -> str:
        return self.Make or ""

    @make.setter
    def make(self, value: str) -> None:
        self.Make = value

    @property
    def capacity(self) -> str:
        return self.Capacity or ""

    @property
    def unit(self) -> str:
        return self.Unit or ""

    @property
    def attribute(self) -> str:
        return self.Attribute or ""

    @property
    def supplier(self) -> str:
        return self.Supplier or ""

    @supplier.setter
    def supplier(self, value: str) -> None:
        self.Supplier = value

    @property
    def base_purchase_rate(self):
        return self.Base_Purchase_Rate or Decimal("0")

    @property
    def discount_percent(self):
        return self.Discount_Percent or Decimal("0")

    @property
    def net_material_rate(self):
        return self.Net_Material_Rate or Decimal("0")

    @property
    def procurement_value(self):
        return self.Procurement_Value

    @property
    def commercial_material_base(self):
        return self.Commercial_Material_Base

    @property
    def accessories_value(self):
        return self.Accessories_Value

    @property
    def handling_value(self):
        return self.Handling_Value

    @property
    def wastage_value(self):
        return self.Wastage_Value

    @property
    def subtotal_before_profit(self):
        return self.Subtotal_Before_Profit

    @property
    def profit_value(self):
        return self.Profit_Value

    @property
    def final_expenditure(self):
        return self.Final_Expenditure

    @property
    def final_amount_excl_gst(self):
        return self.Final_Amount_Excl_GST or Decimal("0")

    @final_amount_excl_gst.setter
    def final_amount_excl_gst(self, value) -> None:
        self.Final_Amount_Excl_GST = value

    @property
    def margin_percent(self):
        return self.Margin_Percent_On_Selling


class Labour_Master(models.Model):
    """Source: Labour_Master sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="labour_master_rows"
    )
    Tech_Key = models.CharField(max_length=255, db_index=True)
    Size = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
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

    _KW_ALIASES = {
        "tech_key": "Tech_Key",
        "size": "Size",
        "labour_type": "Labour_Type",
        "base_rate": "Base_Rate",
        "size_factor": "Size_Factor",
        "labour_rate_per_unit": "Labour_Rate_Per_unit",
        "testing_labour_value": "Testing_Labour_Value",
        "scaffolding_labour_value": "Scaffolding_Labour_Value",
        "consumables_labour_value": "Consumables_Labour_Value",
        "painting_labour_value": "Painting_Labour_Value",
        "labour_buffer_value": "Labour_Buffer_Value",
        "total_labour_per_unit": "Total_Labour_per_Unit",
        "labour_multiplier": "Labour_Multiplier",
        "total_labour_with_multiplier": "Total_Labour_per_unit_with_labour_Multipler",
    }

    def __init__(self, *args, **kwargs):
        for alias, field in self._KW_ALIASES.items():
            if alias in kwargs:
                kwargs[field] = kwargs.pop(alias)
        super().__init__(*args, **kwargs)

    def __str__(self) -> str:
        return self.Tech_Key or ""

    @property
    def tech_key(self) -> str:
        return self.Tech_Key or ""

    @property
    def labour_type(self) -> str:
        return self.Labour_Type or ""

    @property
    def labour_rate_per_unit(self):
        return self.Labour_Rate_Per_unit or Decimal("0")

    @property
    def total_labour_per_unit(self):
        return self.Total_Labour_per_Unit

    @property
    def total_labour_with_multiplier(self):
        return self.Total_Labour_per_unit_with_labour_Multipler


class TOR_Main(models.Model):
    """Source: TOR_Main sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_main_rows"
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

    @property
    def category(self) -> str:
        return (self.Category or "").strip()

    @property
    def project_state(self) -> str:
        return self.Project_State or ""


class Labour_Structure_Source(models.Model):
    """Source: Labour_Structure_Source sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion,
        on_delete=models.CASCADE,
        related_name="labour_structure_rows",
    )
    Category = models.CharField(max_length=255, null=True, blank=True)
    Sub_Category = models.CharField(max_length=255, null=True, blank=True)
    Size = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    Unit = models.CharField(max_length=100, null=True, blank=True)
    Tech_Key = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "Labour_Structure_Source"

    _KW_ALIASES = {
        "category": "Category",
        "sub_category": "Sub_Category",
        "size": "Size",
        "unit": "Unit",
        "tech_key": "Tech_Key",
    }

    def __init__(self, *args, **kwargs):
        for alias, field in self._KW_ALIASES.items():
            if alias in kwargs:
                kwargs[field] = kwargs.pop(alias)
        super().__init__(*args, **kwargs)

    def __str__(self) -> str:
        return self.Tech_Key or ""

    @property
    def category(self) -> str:
        return self.Category or ""

    @property
    def sub_category(self) -> str:
        return self.Sub_Category or ""

    @property
    def size(self):
        return self.Size

    @property
    def unit(self) -> str:
        return self.Unit or ""

    @property
    def tech_key(self) -> str:
        return self.Tech_Key or ""


class TOR_Labour(models.Model):
    """Source: TOR_Labour sheet."""

    database_version = models.ForeignKey(
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_labour_rows"
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
        DatabaseVersion, on_delete=models.CASCADE, related_name="tor_accessories_rows"
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
        DatabaseVersion, on_delete=models.CASCADE, related_name="state_control_rows"
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

    _KW_ALIASES = {
        "state": "State",
        "labour_multiplier": "Labour_Multiplier",
    }

    def __init__(self, *args, **kwargs):
        for alias, field in self._KW_ALIASES.items():
            if alias in kwargs:
                kwargs[field] = kwargs.pop(alias)
        super().__init__(*args, **kwargs)

    def __str__(self) -> str:
        return self.State

    @property
    def state(self) -> str:
        return self.State

    @property
    def labour_multiplier(self):
        return self.Labour_Multiplier


# Workflow aliases used by database import and AI context services.
MaterialRate = Rate_Master
LabourMaster = Labour_Master
CategoryConfig = TOR_Main
LabourConfig = TOR_Labour
AccessoriesRule = TOR_Accessories
StateMultiplier = State_Control_List
LabourStructureSource = Labour_Structure_Source
