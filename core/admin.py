from django.contrib import admin
from .models import Organization, Membership
from .audit import AuditEvent


class OrgAdminMixin:
    """
    Säkerställer att admin endast visar data för aktiv organisation
    och sätter org automatiskt vid skapande.
    """

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        org = getattr(request, "org", None)
        if not org:
            return qs.none()

        return qs.filter(org=org)

    def save_model(self, request, obj, form, change):
        if not obj.org_id:
            obj.org = getattr(request, "org", None)
        super().save_model(request, obj, form, change)


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
