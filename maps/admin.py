from django.contrib import admin

from .models import FishSpecies, MapBoundary, WaterBody


@admin.register(FishSpecies)
class FishSpeciesAdmin(admin.ModelAdmin):
    list_display = ("name", "latin_name")
    search_fields = ("name", "latin_name")
    fields = ("name", "latin_name")


@admin.register(MapBoundary)
class MapBoundaryAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "is_active")
    list_filter = ("org", "is_active")
    search_fields = ("name", "org__name")
    fields = ("org", "name", "geojson", "is_active")


@admin.register(WaterBody)
class WaterBodyAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "water_type", "is_active")
    list_filter = ("org", "water_type", "is_active")
    search_fields = ("name", "description", "org__name", "species__name")
    filter_horizontal = ("species",)
    fields = (
        "org",
        "name",
        "water_type",
        "description",
        "geojson",
        "is_active",
        "species",
    )

