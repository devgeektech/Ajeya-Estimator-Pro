from django.contrib import admin

from .models import (
    DatabaseVersion,
    Labour_master_Output,
    Rate_Master_Output,
)


@admin.register(DatabaseVersion)
class DatabaseVersionAdmin(admin.ModelAdmin):
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

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.is_active:
            from .services.activation import activate_database_version

            activate_database_version(obj)


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
