from django.contrib import admin
from .models import BoardMembership, GovernanceActivityLog, BoardMatter, Meeting, MeetingMatter


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


@admin.register(BoardMatter)
class BoardMatterAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "status", "assigned_to", "created_at")
    list_filter = ("type", "status")
    search_fields = ("title", "description")


@admin.register(MeetingMatter)
class MeetingMatterAdmin(admin.ModelAdmin):
    list_display = ("meeting", "matter", "created_at")
    search_fields = ("meeting__title", "matter__title")
    ordering = ("-created_at",)
