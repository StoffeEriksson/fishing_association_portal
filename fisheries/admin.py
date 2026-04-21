from django.contrib import admin

from .models import ActionArea, ActionComment, ActionLog, Observation, ObservationComment, ObservationLog


@admin.register(ActionArea)
class ActionAreaAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "org",
        "status",
        "priority",
        "responsible_user",
        "deadline",
        "is_active",
    )
    list_filter = ("org", "status", "priority", "is_active")
    search_fields = (
        "name",
        "description",
        "org__name",
        "responsible_user__email",
        "responsible_user__username",
    )
    fieldsets = (
        (
            "Grundinfo",
            {
                "fields": ("org", "name", "description", "status", "priority"),
            },
        ),
        (
            "Koppling",
            {
                "fields": ("water_body", "responsible_user"),
            },
        ),
        (
            "Planering",
            {
                "fields": ("deadline", "estimated_cost", "actual_cost"),
            },
        ),
        (
            "System",
            {
                "fields": ("is_active", "created_by", "updated_by"),
            },
        ),
    )
    raw_id_fields = ("water_body", "responsible_user")


@admin.register(ActionComment)
class ActionCommentAdmin(admin.ModelAdmin):
    list_display = ("action_area", "user", "created_at")
    list_filter = ("org", "created_at")
    search_fields = ("body", "action_area__name")


@admin.register(ActionLog)
class ActionLogAdmin(admin.ModelAdmin):
    list_display = ("action_area", "event_type", "user", "created_at")
    list_filter = ("org", "event_type", "created_at")
    search_fields = ("message", "action_area__name")


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = ("title", "org", "category", "status", "water_body", "linked_action", "is_active")
    list_filter = ("org", "category", "status", "is_active")
    search_fields = ("title", "description", "water_body__name", "linked_action__name")
    fields = (
        "org",
        "title",
        "category",
        "water_body",
        "linked_action",
        "description",
        "status",
        "created_by",
        "updated_by",
        "is_active",
    )
    raw_id_fields = ("water_body", "linked_action")


@admin.register(ObservationComment)
class ObservationCommentAdmin(admin.ModelAdmin):
    list_display = ("observation", "user", "created_at")
    list_filter = ("org", "created_at")
    search_fields = ("body", "observation__title")


@admin.register(ObservationLog)
class ObservationLogAdmin(admin.ModelAdmin):
    list_display = ("observation", "event_type", "user", "created_at")
    list_filter = ("org", "event_type", "created_at")
    search_fields = ("message", "observation__title")

