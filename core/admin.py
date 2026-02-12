from django.contrib import admin
from .models import Organization, Membership
from .audit import AuditEvent


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "org_number", "is_active", "created_at")
    search_fields = ("name", "org_number")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "is_active", "created_at")
    list_filter = ("role", "is_active")
    search_fields = ("user__username", "organization__name")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "org", "actor", "action", "entity", "entity_id")
    list_filter = ("action", "entity", "org")
    search_fields = ("entity_id", "message", "actor__username")
    readonly_fields = ("created_at",)
