from django.contrib import admin

from .models import (
    DatabaseVersion,
    LabourMaster,
    LabourStructureSource,
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
admin.site.register(ProductAlias)


@admin.register(ProductEmbedding)
class ProductEmbeddingAdmin(admin.ModelAdmin):
    list_display = (
        "tech_key",
        "database_version_id",
        "rate_master_id",
        "chroma_id",
        "embedding_model",
        "generated_at",
    )
    search_fields = ("tech_key", "chroma_id", "embedding_model")
    list_filter = ("database_version_id", "embedding_model")
