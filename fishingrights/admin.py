from django.contrib import admin
from .models import Property, RightHolder, FishingRightShare


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("designation", "org", "external_id", "created_at")
    search_fields = ("designation", "external_id")
    list_filter = ("org",)


@admin.register(RightHolder)
class RightHolderAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "email", "created_at")
    search_fields = ("name", "email")
    list_filter = ("org",)


@admin.register(FishingRightShare)
class FishingRightShareAdmin(admin.ModelAdmin):
    list_display = ("property", "holder", "share", "org", "created_at")
    search_fields = ("property__designation", "holder__name")
    list_filter = ("org",)
