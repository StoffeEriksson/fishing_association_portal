from django.contrib import admin

from .models import FishSpecies, MapBoundary, WaterBody, WaterBodyHealthSnapshot


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


@admin.register(WaterBodyHealthSnapshot)
class WaterBodyHealthSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "water_body",
        "org",
        "eco_tone",
        "chem_tone",
        "risk_flag",
        "fetched_at",
    )
    list_filter = ("org", "eco_tone", "chem_tone", "risk_flag")
    search_fields = ("water_body__name", "water_body__viss_ms_cd", "org__name")
    readonly_fields = ("created_at", "updated_at", "fetched_at")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "org",
                    "water_body",
                    "source",
                    "fetched_at",
                    "fetch_error",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "eco_status",
                    "eco_tone",
                    "chem_status",
                    "chem_tone",
                    "risk",
                    "risk_flag",
                    "fish",
                    "fish_tone",
                    "mkn",
                ),
            },
        ),
        (
            "Rådata",
            {
                "classes": ("collapse",),
                "fields": ("raw_payload",),
            },
        ),
        (
            "Metadata",
            {
                "classes": ("collapse",),
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

