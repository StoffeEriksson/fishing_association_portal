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
    list_display = (
        "name",
        "water_type",
        "org",
        "viss_ms_cd",
        "viss_eu_cd",
        "is_active",
    )
    list_filter = ("water_type", "is_active", "external_source", "org")
    search_fields = ("name", "viss_ms_cd", "viss_eu_cd", "description", "org__name", "species__name")
    filter_horizontal = ("species",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "org",
                    "name",
                    "water_type",
                    "description",
                    "geojson",
                    "is_active",
                    "species",
                ),
            },
        ),
        (
            "VISS / extern källa",
            {
                "classes": ("collapse",),
                "fields": (
                    "viss_ms_cd",
                    "viss_eu_cd",
                    "external_source",
                    "geometry_source",
                    "source_name",
                    "imported_at",
                ),
            },
        ),
    )

