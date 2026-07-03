from django.contrib import admin

from .models import (
    DatabaseVersion,
    LabourMaster,
    ProductAlias,
    ProductEmbedding,
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
    list_display = ("product_code", "make", "vendor", "purchase_rate", "unit", "database_version")
    search_fields = ("product_code", "description", "make", "vendor")
    list_filter = ("database_version", "category")


@admin.register(LabourMaster)
class LabourMasterAdmin(admin.ModelAdmin):
    list_display = ("labour_code", "labour_name", "labour_rate", "unit", "database_version")
    search_fields = ("labour_code", "labour_name")


admin.site.register(TORMain)
admin.site.register(TORLabour)
admin.site.register(TORAccessories)
admin.site.register(StateControl)
admin.site.register(ProductAlias)
admin.site.register(ProductEmbedding)
