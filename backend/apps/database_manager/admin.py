from django.contrib import admin

from .models import (
    DatabaseVersion,
    Labour_master_Output,
    Product_Helper,
    Rate_Master_Output,
)


@admin.register(DatabaseVersion)
class DatabaseVersionAdmin(admin.ModelAdmin):
    """Read-mostly. Activation must go through the embedding-gated import UI."""

    list_display = (
        "version_number",
        "name",
        "is_active",
        "uploaded_by",
        "uploaded_at",
        "source_filename",
    )
    list_filter = ("is_active",)
    search_fields = ("name", "source_filename")
    readonly_fields = (
        "version_number",
        "is_active",
        "uploaded_by",
        "uploaded_at",
        "source_filename",
        "file",
    )


@admin.register(Product_Helper)
class ProductHelperAdmin(admin.ModelAdmin):
    list_display = (
        "Product_ID",
        "Category",
        "Sub_Category",
        "Class",
        "Size",
        "Unit",
        "Status",
        "database_version",
    )
    list_filter = ("Category", "Status", "database_version")
    search_fields = (
        "Product_ID",
        "Category",
        "Sub_Category",
        "Class",
        "Attribute",
    )


@admin.register(Rate_Master_Output)
class RateMasterOutputAdmin(admin.ModelAdmin):
    list_display = (
        "Rate_ID",
        "Product_ID",
        "Category",
        "Sub_Category",
        "Make",
        "Vendor",
        "Final_Material_Amount",
        "database_version",
    )
    list_filter = ("Category", "database_version")
    search_fields = (
        "Product_ID",
        "Rate_ID",
        "Category",
        "Sub_Category",
        "Make",
        "Vendor",
    )


@admin.register(Labour_master_Output)
class LabourMasterOutputAdmin(admin.ModelAdmin):
    list_display = (
        "Product_ID",
        "Category",
        "Sub_Category",
        "Labour_Type",
        "Total_Labour_per_unit_with_labour_Multipler",
        "database_version",
    )
    list_filter = ("Labour_Type", "database_version")
    search_fields = ("Product_ID", "Category", "Sub_Category", "Labour_Type")
