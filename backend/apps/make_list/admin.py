from django.contrib import admin

from .models import MakeListEntry


@admin.register(MakeListEntry)
class MakeListEntryAdmin(admin.ModelAdmin):
    list_display = ("make", "category", "boq_run")
    search_fields = ("make",)
