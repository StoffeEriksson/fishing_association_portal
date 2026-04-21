from django.db import models
from django.contrib.auth import get_user_model

from core.tenancy import OrgModel
from maps.models import WaterBody

User = get_user_model()


class ActionStatus(models.TextChoices):
    URGENT = "urgent", "Urgent"
    NEEDS_ACTION = "needs_action", "Needs action"
    PLANNED = "planned", "Planned"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"


class ActionPriority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class ActionArea(OrgModel):
    name = models.CharField(max_length=255)
    geojson = models.JSONField()
    status = models.CharField(
        max_length=50,
        choices=ActionStatus.choices,
        default=ActionStatus.NEEDS_ACTION,
    )
    water_body = models.ForeignKey(
        WaterBody,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_areas",
    )
    responsible_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_actions",
    )
    priority = models.CharField(
        max_length=30,
        choices=ActionPriority.choices,
        default=ActionPriority.MEDIUM,
    )
    deadline = models.DateField(null=True, blank=True)
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    actual_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_actions",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_actions",
    )

    def __str__(self):
        return self.name


class ActionComment(OrgModel):
    action_area = models.ForeignKey(
        ActionArea,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    body = models.TextField()

    def __str__(self):
        return self.body[:50]


class ActionLog(OrgModel):
    action_area = models.ForeignKey(
        ActionArea,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    event_type = models.CharField(max_length=50)
    message = models.TextField(blank=True)
    from_status = models.CharField(max_length=50, blank=True)
    to_status = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"{self.event_type} {self.created_at:%Y-%m-%d %H:%M}"


class ObservationCategory(models.TextChoices):
    FISH_STOCK = "fish_stock", "Fish stock"
    HABITAT = "habitat", "Habitat"
    WATER_QUALITY = "water_quality", "Water quality"
    ILLEGAL_FISHING = "illegal_fishing", "Illegal fishing"
    INFRASTRUCTURE = "infrastructure", "Infrastructure"
    OTHER = "other", "Other"


class ObservationStatus(models.TextChoices):
    NEW = "new", "New"
    UNDER_REVIEW = "under_review", "Under review"
    LINKED_TO_ACTION = "linked_to_action", "Linked to action"
    CLOSED = "closed", "Closed"


class Observation(OrgModel):
    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=50,
        choices=ObservationCategory.choices,
        default=ObservationCategory.OTHER,
    )
    water_body = models.ForeignKey(
        "maps.WaterBody",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="observations",
    )
    linked_action = models.ForeignKey(
        "ActionArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="observations",
    )
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=50,
        choices=ObservationStatus.choices,
        default=ObservationStatus.NEW,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_observations",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_observations",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title


class ObservationComment(OrgModel):
    observation = models.ForeignKey(
        Observation,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    body = models.TextField()

    def __str__(self):
        return self.body[:50]


class ObservationLog(OrgModel):
    observation = models.ForeignKey(
        Observation,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    event_type = models.CharField(max_length=50)
    message = models.TextField(blank=True)

    def __str__(self):
        return f"{self.event_type} {self.created_at:%Y-%m-%d %H:%M}"

