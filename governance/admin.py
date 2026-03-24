from django.contrib import admin
from .models import BoardMembership, GovernanceActivityLog


@admin.register(BoardMembership)
class BoardMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "org", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "user__username")


@admin.register(GovernanceActivityLog)
class GovernanceActivityLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "target_user", "org", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("user__email", "target_user__email", "message")
    ordering = ("-created_at",)
