from django.contrib import admin

from .labels import (
    get_action_priority_label,
    get_action_status_label,
    get_observation_category_label,
    get_observation_status_label,
)
from .models import (
    ActionArea,
    ActionComment,
    ActionLog,
    ActionPriority,
    ActionStatus,
    FisheriesImage,
    Observation,
    ObservationCategory,
    ObservationComment,
    ObservationLog,
    ObservationStatus,
)


@admin.register(ActionArea)
class ActionAreaAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "org",
        "status_display",
        "priority_display",
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
            "Kartposition",
            {
                "fields": ("latitude", "longitude"),
                "classes": ("collapse",),
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

    @admin.display(description="Status", ordering="status")
    def status_display(self, obj):
        return get_action_status_label(obj.status)

    @admin.display(description="Prioritet", ordering="priority")
    def priority_display(self, obj):
        return get_action_priority_label(obj.priority)

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        formfield = super().formfield_for_choice_field(db_field, request, **kwargs)
        if db_field.name == "status":
            formfield.choices = [
                (value, get_action_status_label(value))
                for value, _ in ActionStatus.choices
            ]
        elif db_field.name == "priority":
            formfield.choices = [
                (value, get_action_priority_label(value))
                for value, _ in ActionPriority.choices
            ]
        return formfield


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
    list_display = (
        "title",
        "org",
        "category_display",
        "status_display",
        "water_body",
        "linked_action",
        "is_active",
    )

    @admin.display(description="Kategori", ordering="category")
    def category_display(self, obj):
        return get_observation_category_label(obj.category)

    @admin.display(description="Status", ordering="status")
    def status_display(self, obj):
        return get_observation_status_label(obj.status)

    list_filter = ("org", "category", "status", "is_active")
    search_fields = ("title", "description", "water_body__name", "linked_action__name")
    fieldsets = (
        (
            None,
            {
                "fields": (
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
                ),
            },
        ),
        (
            "Kartposition",
            {
                "fields": ("latitude", "longitude"),
                "classes": ("collapse",),
            },
        ),
    )
    raw_id_fields = ("water_body", "linked_action")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        formfield = super().formfield_for_choice_field(db_field, request, **kwargs)
        if db_field.name == "category":
            formfield.choices = [
                (value, get_observation_category_label(value))
                for value, _ in ObservationCategory.choices
            ]
        elif db_field.name == "status":
            formfield.choices = [
                (value, get_observation_status_label(value))
                for value, _ in ObservationStatus.choices
            ]
        return formfield


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


@admin.register(FisheriesImage)
class FisheriesImageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "org",
        "image_type",
        "observation",
        "action",
        "comment",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("org", "image_type", "created_at")
    search_fields = (
        "caption",
        "observation__title",
        "action__name",
        "comment__body",
    )
