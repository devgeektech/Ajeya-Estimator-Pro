from django.contrib import admin

from .models import (
    DatabaseVersion,
    LabourMaster,
    LabourStructureSource,
    RateMaster,
    StateControl,
    TORAccessories,
    TORLabour,
    TORMain,
)


@admin.register(DatabaseVersion)
class DatabaseVersionAdmin(admin.ModelAdmin):
    list_display = ("version_number", "is_active", "uploaded_by", "uploaded_at", "source_filename")
    list_filter = ("is_active",)


@admin.register(RateMaster)
class RateMasterAdmin(admin.ModelAdmin):
    list_display = (
        "tech_key",
        "category",
        "sub_category",
        "make",
        "supplier",
        "net_material_rate",
        "final_amount_excl_gst",
        "unit",
        "database_version",
    )
    search_fields = ("tech_key", "category", "sub_category", "make", "supplier")
    list_filter = ("database_version", "category", "sub_category")


@admin.register(LabourMaster)
class LabourMasterAdmin(admin.ModelAdmin):
    list_display = ("tech_key", "state", "category", "sub_category", "total_labour_with_multiplier", "unit", "database_version")
    search_fields = ("tech_key", "labour_type", "category", "sub_category")


admin.site.register(TORMain)
admin.site.register(LabourStructureSource)
admin.site.register(TORLabour)
admin.site.register(TORAccessories)
admin.site.register(StateControl)
