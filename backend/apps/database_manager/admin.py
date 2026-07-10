from django.contrib import admin



from .models import (

    DatabaseVersion,

    Labour_Master,

    Labour_Structure_Source,

    Rate_Master,

    State_Control_List,

    TOR_Accessories,

    TOR_Labour,

    TOR_Main,

)





@admin.register(DatabaseVersion)

class DatabaseVersionAdmin(admin.ModelAdmin):

    list_display = ("version_number", "is_active", "uploaded_by", "uploaded_at", "source_filename")

    list_filter = ("is_active",)



    def save_model(self, request, obj, form, change):

        super().save_model(request, obj, form, change)

        if obj.is_active:

            from .services.activation import activate_database_version



            activate_database_version(obj)





@admin.register(Rate_Master)

class RateMasterAdmin(admin.ModelAdmin):

    list_display = (

        "Tech_Key",

        "Category",

        "Sub_Category",

        "Make",

        "Supplier",

        "Net_Material_Rate",

        "Final_Amount_Excl_GST",

        "Unit",

        "database_version",

    )

    search_fields = ("Tech_Key", "Category", "Sub_Category", "Make", "Supplier")

    list_filter = ("database_version", "Category", "Sub_Category")





@admin.register(Labour_Master)

class LabourMasterAdmin(admin.ModelAdmin):

    list_display = (

        "Tech_Key",

        "Labour_Type",

        "Total_Labour_per_unit_with_labour_Multipler",

        "database_version",

    )

    search_fields = ("Tech_Key", "Labour_Type")





admin.site.register(TOR_Main)

admin.site.register(Labour_Structure_Source)

admin.site.register(TOR_Labour)

admin.site.register(TOR_Accessories)

admin.site.register(State_Control_List)

